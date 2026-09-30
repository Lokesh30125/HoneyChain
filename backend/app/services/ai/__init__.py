"""HoneyChain AI analysis engine (baseline, rule-based).

Public surface:

* :class:`~app.services.ai.engine.AiEngine` — ``analyze(readings, hive=...,
  now=...)`` returns an :class:`~app.services.ai.types.AnalysisResult`.
* The dataclasses in :mod:`app.services.ai.types`.
* The reference constants in :mod:`app.services.ai.thresholds`.

Everything under this package is deliberately free of database and HTTP
concerns: it takes readings in and gives a result back. Persistence, staleness
policy, authorization and alert lifecycle live in ``AiService`` and
``AiAlertService``.
"""

from app.services.ai.engine import AiEngine
from app.services.ai.types import AnalysisResult

__all__ = ["AiEngine", "AnalysisResult"]
