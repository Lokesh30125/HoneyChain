"""AI routes — a thin HTTP layer over :class:`app.services.ai_service.AiService`.

Authorisation is declarative: a beekeeper reaches these endpoints through
``AI_READ_SELF`` / ``AI_ANALYZE_SELF``, KVIC officers and administrators through
the ``_ALL`` pair, and a consumer holds neither, so the module answers 403 before
any handler body runs. The service then narrows every query to the caller's own
apiary — knowing a hive id is never enough to read its analysis.

Endpoints
---------
* ``GET  /ai/summary``                      fleet counters for the AI screens
* ``GET  /ai/hives``                        one row per hive in scope, with AI state
* ``GET  /ai/hives/{hive_id}``              the insight for one hive (read-through)
* ``POST /ai/hives/{hive_id}/analyze``      run the engine for one hive
* ``POST /ai/analyze``                      run the engine over every hive in scope
* ``GET  /ai/hives/{hive_id}/history``      stored analyses, newest first
* ``GET  /ai/hives/{hive_id}/alerts``       alerts recorded for one hive
* ``GET  /ai/alerts``                       alerts in scope, filterable
* ``GET  /ai/alerts/summary``               alert counters
* ``GET  /ai/alerts/{alert_id}``            one alert
* ``POST /ai/alerts/{alert_id}/acknowledge``   record that a human has seen it
* ``POST /ai/alerts/{alert_id}/resolve``       close it
* ``POST /ai/alerts/{alert_id}/reopen``        put it back
* ``POST /ai/analyze``                      run the engine over every hive in scope

A note on ``GET /ai/hives/{hive_id}``: it may compute and store an analysis when
there is none, when the stored one is stale, or when enough new telemetry has
arrived — but only while ``AI_AUTO_ANALYSIS_ENABLED`` is true and only for a
caller holding an analyse permission. ``?refresh=false`` reads without writing.
The response always says what happened in ``computed`` and ``compute_reason``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.config import get_settings
from app.core.permissions import Permission, require_any_permission
from app.models.enums import AiAlertSeverity, AiAlertStatus
from app.models.user import User
from app.schemas.ai import (
    AiAlertPublic,
    AiAlertSummary,
    AiAnalysisRunResult,
    AiBulkRunResult,
    AiEngineSummary,
    AiModelInfo,
    AlertActionRequest,
    AnalysisRequest,
    HiveAiAnalysisPublic,
    HiveAiInsight,
    HiveAiSummaryRow,
    empty_insight,
    to_alert_public,
    to_analysis_public,
    to_insight,
    to_run_result,
    to_summary_row,
)
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.services.ai_alert_service import AiAlertService
from app.services.ai_service import AiService
from app.services.hive_service import HiveService

router = APIRouter(prefix="/ai", tags=["AI Insights"])

#: Reading assessments needs either scope; producing them needs an analyse scope.
READ_AI = require_any_permission(Permission.AI_READ_SELF, Permission.AI_READ_ALL)
ANALYZE_AI = require_any_permission(Permission.AI_ANALYZE_SELF, Permission.AI_ANALYZE_ALL)


def _model_info() -> AiModelInfo:
    settings = get_settings()
    return AiModelInfo(
        type=settings.AI_MODEL_TYPE,
        version=settings.AI_MODEL_VERSION,
        baseline=True,
        note=(
            "Rule-based baseline model. Scores describe recorded sensor patterns against "
            "reference bands; they are monitoring indicators, not diagnoses."
        ),
    )


# --------------------------------------------------------------------------- #
# Fleet overview
# --------------------------------------------------------------------------- #
@router.get(
    "/summary",
    response_model=ApiResponse[AiEngineSummary],
    summary="AI overview for the caller's hives",
    description=(
        "Health bands, risk bands, projected yield and open-alert counts, counted in SQL over "
        "each hive's **latest** analysis. A beekeeper sees their own apiary; staff see the "
        "platform. Every counter is derived from stored rows — nothing is estimated, and an "
        "account with no telemetry reports zeros."
    ),
)
def read_summary(
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    settings = get_settings()
    service = AiService(session, settings)
    payload = service.summary(actor)
    return ok(
        AiEngineSummary(
            total_hives=payload["total_hives"],
            analysed_hives=payload["analysed_hives"],
            hives_without_analysis=payload["hives_without_analysis"],
            hives_with_telemetry=payload["hives_with_telemetry"],
            health=payload["health"],
            disease_risk=payload["disease_risk"],
            swarming_risk=payload["swarming_risk"],
            yield_projection=payload["yield"],
            open_alerts=payload["open_alerts"],
            alerts_by_severity=payload["alerts_by_severity"],
            model=_model_info(),
            auto_analysis_enabled=settings.AI_AUTO_ANALYSIS_ENABLED,
            analysis_window_hours=settings.AI_ANALYSIS_WINDOW_HOURS,
            generated_at=datetime.now(timezone.utc),
        )
    )


@router.get(
    "/hives",
    response_model=ApiResponse[list[HiveAiSummaryRow]],
    summary="AI state of every hive in scope",
    description=(
        "One row per hive, carrying the latest analysis (if any) and its open-alert count. "
        "Hives that have never been analysed are returned with ``analyzed: false`` rather than "
        "omitted, so the screen can show them as 'not analysed yet'."
    ),
)
def list_hive_analysis(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Hive code or district."),
    only_with_analysis: bool = Query(default=False),
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    hives = service.scoped_hives(actor)
    if search:
        needle = search.strip().lower()
        hives = [
            hive
            for hive in hives
            if needle in (hive.hive_code or "").lower()
            or needle in (hive.district or "").lower()
        ]

    latest = service.latest_for_hives([hive.id for hive in hives])
    alert_service = AiAlertService(session)
    rows = [
        to_summary_row(
            hive,
            latest.get(hive.id),
            open_alerts=len(alert_service.list_for_hive(hive.id, limit=100)),
        )
        for hive in hives
    ]
    if only_with_analysis:
        rows = [row for row in rows if row.analyzed]

    rows.sort(key=lambda row: (not row.analyzed, row.hive_code))
    total = len(rows)
    paged = rows[pagination.offset : pagination.offset + pagination.page_size]
    return paginated(
        [row.model_dump() for row in paged],
        total_items=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "/analyze",
    response_model=ApiResponse[AiBulkRunResult],
    summary="Analyse every hive in scope",
    description=(
        "Runs the engine over each hive the caller can see, sequentially and synchronously. "
        "Intended as a manual 'refresh everything' action for a beekeeper's own apiary, not as a "
        "platform-wide job."
    ),
)
def analyse_all(
    payload: AnalysisRequest | None = None,
    actor: User = Depends(ANALYZE_AI),
    session: Session = Depends(db_session),
) -> dict:
    result = AiService(session, get_settings()).analyse_all(
        actor, note=payload.reason if payload else None
    )
    # The service already returns the model identity alongside the counters, so
    # it is passed straight through rather than rebuilt here.
    return ok(AiBulkRunResult(**result))


# --------------------------------------------------------------------------- #
# Per-hive insights
# --------------------------------------------------------------------------- #
@router.get(
    "/hives/{hive_id}",
    response_model=ApiResponse[HiveAiInsight],
    summary="AI insight for one hive",
    description=(
        "Returns the newest stored assessment, together with the factors, indicators and "
        "recommendations behind it. When there is no stored assessment — or the stored one is "
        "stale, or enough new telemetry has arrived — a fresh analysis is computed and stored, "
        "provided auto-analysis is enabled and the caller may analyse. Pass ``refresh=false`` to "
        "read without writing, or ``refresh=true`` to force a recomputation. The response always "
        "reports what happened in ``computed`` and ``compute_reason``. A hive with no telemetry "
        "returns ``data_quality: INSUFFICIENT`` with null scores and a plain-language reason, "
        "never a placeholder score."
    ),
)
def read_hive_insight(
    hive_id: uuid.UUID,
    refresh: bool | None = Query(
        default=None,
        description="true forces an analysis, false reads the stored one, omitted applies the policy.",
    ),
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    settings = get_settings()
    service = AiService(session, settings)
    hive = service.get_hive_for_user(actor, hive_id)
    analysis, meta = service.snapshot_for_hive(hive, user=actor, refresh=refresh)
    freshness = service.freshness(analysis)

    if analysis is None:
        # No stored analysis and auto-analysis is off (or the caller may not
        # analyse): report the honest empty state rather than an error, and never
        # a zero that looks like a measurement.
        return ok(
            empty_insight(
                hive,
                meta=meta,
                freshness=freshness,
                model_type=settings.AI_MODEL_TYPE,
                model_version=settings.AI_MODEL_VERSION,
            )
        )

    return ok(to_insight(analysis, hive=hive, meta=meta, freshness=freshness))


@router.post(
    "/hives/{hive_id}/analyze",
    response_model=ApiResponse[AiAnalysisRunResult],
    summary="Run the AI analysis for one hive",
    description=(
        "Runs the engine over the configured window (default seven days) and stores the result. "
        "The window, thresholds and model version are platform settings, not request parameters, "
        "so a thin dataset cannot be made to look confident. Returns the stored outcome including "
        "how many alerts were raised, bumped or resolved."
    ),
)
def analyze_hive(
    hive_id: uuid.UUID,
    payload: AnalysisRequest | None = None,
    actor: User = Depends(ANALYZE_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    hive = service.get_hive_for_user(actor, hive_id)
    analysis, counters = service.analyze_hive(
        hive, user=actor, note=payload.reason if payload else None
    )
    return ok(to_run_result(hive, analysis, counters))


@router.get(
    "/hives/{hive_id}/history",
    response_model=ApiResponse[list[HiveAiAnalysisPublic]],
    summary="Stored analyses for one hive",
    description="Newest first. Each row is a complete assessment, so a trend over time can be read without recomputation.",
)
def read_hive_history(
    hive_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    hive = service.get_hive_for_user(actor, hive_id)
    rows, total = service.history_for_hive(
        hive.id, limit=pagination.page_size, offset=pagination.offset
    )
    return paginated(
        [to_analysis_public(row, hive_code=hive.hive_code).model_dump() for row in rows],
        total_items=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/hives/{hive_id}/alerts",
    response_model=ApiResponse[list[AiAlertPublic]],
    summary="Alerts recorded for one hive",
    description="Open and acknowledged alerts by default; pass ``include_resolved=true`` for the full record.",
)
def read_hive_alerts(
    hive_id: uuid.UUID,
    include_resolved: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    hive = service.get_hive_for_user(actor, hive_id)
    alerts = AiAlertService(session).list_for_hive(
        hive.id, include_resolved=include_resolved, limit=limit
    )
    return ok(
        [to_alert_public(alert, hive_code=hive.hive_code).model_dump() for alert in alerts]
    )


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
@router.get(
    "/alerts",
    response_model=ApiResponse[list[AiAlertPublic]],
    summary="List AI alerts",
    description=(
        "Alerts in the caller's scope: a beekeeper sees alerts for their own hives, staff see "
        "every alert. By default this returns alerts that still need attention (OPEN and "
        "ACKNOWLEDGED); pass ``include_resolved=true`` or an explicit ``status`` for the full "
        "history."
    ),
)
def list_alerts(
    pagination: PaginationParams = Depends(),
    status: AiAlertStatus | None = Query(default=None),
    severity: AiAlertSeverity | None = Query(default=None),
    alert_type: str | None = Query(default=None, max_length=40),
    hive_id: uuid.UUID | None = Query(default=None),
    include_resolved: bool = Query(default=False),
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    if hive_id is not None:
        # Raises 404 for a hive outside scope rather than silently returning nothing.
        service.get_hive_for_user(actor, hive_id)

    alert_service = AiAlertService(session)
    rows, total = alert_service.list_items(
        actor,
        hive_id=hive_id,
        status=status,
        severity=severity,
        alert_type=alert_type.strip().upper() if alert_type else None,
        include_resolved=include_resolved,
        limit=pagination.page_size,
        offset=pagination.offset,
    )
    codes = {hive.id: hive.hive_code for hive in service.scoped_hives(actor)}
    return paginated(
        [to_alert_public(alert, hive_code=codes.get(alert.hive_id)).model_dump() for alert in rows],
        total_items=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/alerts/summary",
    response_model=ApiResponse[AiAlertSummary],
    summary="Alert counters",
    description=(
        "Open alerts by severity for the caller's scope. HoneyChain records alerts in the app and "
        "sends no notifications in this phase — the response says so explicitly."
    ),
)
def alert_summary(
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    payload = AiAlertService(session, get_settings()).summary(actor)
    return ok(AiAlertSummary(**payload))


@router.get(
    "/alerts/{alert_id}",
    response_model=ApiResponse[AiAlertPublic],
    summary="Read one alert",
    description="An alert outside the caller's scope returns 404, not 403.",
)
def read_alert(
    alert_id: uuid.UUID,
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    alert = AiAlertService(session, get_settings()).get_for_user(actor, alert_id)
    hive = service.hives.get(alert.hive_id)
    return ok(to_alert_public(alert, hive_code=hive.hive_code if hive else None))


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=ApiResponse[AiAlertPublic],
    summary="Acknowledge an alert",
    description=(
        "Records that a human has seen the alert. It stays in the list until it is resolved or "
        "the signal stops recurring, and the acknowledgement is written to the audit log."
    ),
)
def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: AlertActionRequest | None = None,
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    alert = AiAlertService(session, get_settings()).acknowledge(
        actor, alert_id, note=payload.note if payload else None
    )
    hive = service.hives.get(alert.hive_id)
    return ok(to_alert_public(alert, hive_code=hive.hive_code if hive else None))


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=ApiResponse[AiAlertPublic],
    summary="Resolve an alert",
    description=(
        "Closes the alert. A signal that recurs after the cooldown window opens a new alert, so "
        "resolving one is a decision about this episode, not a mute."
    ),
)
def resolve_alert(
    alert_id: uuid.UUID,
    payload: AlertActionRequest | None = None,
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    alert = AiAlertService(session, get_settings()).resolve(
        actor, alert_id, note=payload.note if payload else None
    )
    hive = service.hives.get(alert.hive_id)
    return ok(to_alert_public(alert, hive_code=hive.hive_code if hive else None))


@router.post(
    "/alerts/{alert_id}/reopen",
    response_model=ApiResponse[AiAlertPublic],
    summary="Reopen an alert",
    description="Returns a resolved alert to OPEN so it appears in the active list again.",
)
def reopen_alert(
    alert_id: uuid.UUID,
    actor: User = Depends(READ_AI),
    session: Session = Depends(db_session),
) -> dict:
    service = AiService(session, get_settings())
    alert = AiAlertService(session, get_settings()).reopen(actor, alert_id)
    hive = service.hives.get(alert.hive_id)
    return ok(to_alert_public(alert, hive_code=hive.hive_code if hive else None))


__all__ = ["router"]
