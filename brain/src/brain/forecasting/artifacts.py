"""Storing and loading models safely (research R-11, P-3).

The nightly LightGBM booster is saved in LightGBM's own plain-text model format, with its SHA-256,
the LightGBM version, the feature names and the parameters. It is loaded only with
`lightgbm.Booster(model_str=…)` after every check passes. No format that runs code on load.
"""

import hashlib
from datetime import date, timedelta
from typing import Any

import lightgbm as lgb
from sqlalchemy import delete
from sqlalchemy.orm import Session

from brain.clock import now_utc
from brain.forecasting.features import FEATURES
from brain.models import ModelArtifact

FORMAT = "lightgbm-text"


class ArtifactRefused(Exception):
    """The stored model text failed a check and must not be loaded."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save(
    session: Session,
    booster: lgb.Booster,
    run_id: int,
    trained_through: date,
    params: dict[str, Any],
) -> ModelArtifact:
    body = booster.model_to_string()
    row = ModelArtifact(
        job_run_id=run_id,
        format=FORMAT,
        body=body,
        sha256=_sha256(body),
        lightgbm_version=lgb.__version__,
        feature_names=list(booster.feature_name()),
        params=params,
        trained_through=trained_through,
        created_at=now_utc(),
    )
    session.add(row)
    session.flush()
    return row


def load(row: ModelArtifact, expected_features: list[str] = FEATURES) -> lgb.Booster:
    if row.format != FORMAT:
        raise ArtifactRefused(f"unknown model format {row.format!r}")
    if _sha256(row.body) != row.sha256:
        raise ArtifactRefused("the model text does not match its SHA-256")
    if row.lightgbm_version != lgb.__version__:
        raise ArtifactRefused(
            f"saved with LightGBM {row.lightgbm_version}, running {lgb.__version__}"
        )
    if list(row.feature_names) != list(expected_features):
        raise ArtifactRefused("the feature names differ from the running code")
    return lgb.Booster(model_str=row.body)


def prune(session: Session, keep_nights: int, today: date) -> int:
    """Delete artifacts trained more than `keep_nights` nights ago (working files, not a log)."""
    oldest = today - timedelta(days=keep_nights)
    result = session.execute(delete(ModelArtifact).where(ModelArtifact.trained_through < oldest))
    return result.rowcount or 0
