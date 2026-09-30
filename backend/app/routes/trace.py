"""The customer's traceability route — what a QR code resolves to.

    GET  /trace/{package_code}          the journey of the honey in that package
    GET  /trace/{package_code}/qr.svg   the label itself, for the page that prints it

Deliberately unauthenticated: the person holding the jar is not a HoneyChain
user, and asking them to register before they can find out where their honey came
from would defeat the point of putting a code on the lid. What that means is
that everything behind this route is built to be safe for a stranger to see:

* only the package's own supply chain is resolved — the code is the query;
* the payload is assembled from an allow-list in :mod:`app.services.blockchain.service`
  and contains no account, no email, no internal identifier, no note, no
  document, no telemetry and no laboratory detail beyond the result;
* the ledger section shows the event types, their moments and their transaction
  ids — the public half of the chain — and never the submitted payloads;
* there is no listing endpoint here. One code resolves one package; nothing can
  be enumerated by walking this route.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.exceptions import NotFoundError
from app.schemas.blockchain import PublicTrace
from app.schemas.common import ApiResponse, ok
from app.services.blockchain import BlockchainService
from app.services.blockchain.qr import qr_svg

router = APIRouter(tags=["Traceability"])


@router.get(
    "/trace/{package_code}",
    response_model=ApiResponse[PublicTrace],
    summary="Trace a package from its QR",
    description=(
        "The complete journey of the honey in one package: where it was harvested, what was "
        "done to it, what the laboratory found, how it was packed, where it was shipped — and "
        "the blockchain ledger of those events. Only stages that actually happened are "
        "reported as complete."
    ),
)
def trace_package(
    package_code: str,
    session: Session = Depends(db_session),
) -> dict:
    service = BlockchainService(session)
    try:
        payload = service.public_trace(package_code)
    except LookupError as error:
        raise NotFoundError(str(error), details={"resource": "package"}) from error
    return ok(payload)


@router.get(
    "/verify/{code}",
    response_model=ApiResponse[PublicTrace],
    summary="Verify a package by its QR id",
    description=(
        "The same answer as ``GET /trace/{package_code}``, reached by the id printed "
        "beside the code on the label (``QR-HC-PKG-…``) as well as by the package "
        "code itself. One implementation, two names: a scanner that stores the QR id "
        "and a link that carries the package code must resolve to the same jar."
    ),
)
def verify_package(code: str, session: Session = Depends(db_session)) -> dict:
    return trace_package(code, session)


@router.get(
    "/trace/{package_code}/qr.svg",
    summary="A package's QR label",
    description=(
        "The QR image for the package, generated from the link stored on the record. Served "
        "as an image so it can be printed directly, and regenerated from the same stored "
        "value on every request — the label and the record can never disagree."
    ),
    response_class=Response,
)
def trace_package_qr(package_code: str, session: Session = Depends(db_session)) -> Response:
    service = BlockchainService(session)
    package = service.package_for_trace(package_code)
    if package is None:
        raise NotFoundError(
            f"No package matches {package_code}", details={"resource": "package"}
        )
    if str(package.status) == "CANCELLED":
        # A withdrawn package has no public identity to print.
        raise NotFoundError(
            f"No package matches {package_code}", details={"resource": "package"}
        )
    if not package.qr_payload:
        # The page was opened without a QR ever being issued. Issue it now rather
        # than returning a blank label: the code that was printed has to resolve,
        # and issuing records the event exactly once either way.
        service.ensure_qr(package, actor=None)
        service.session.commit()
    return Response(
        content=qr_svg(package.qr_payload or ""),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


__all__ = ["router"]
