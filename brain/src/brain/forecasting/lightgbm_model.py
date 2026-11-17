"""The one global LightGBM model (README 4.2, research R-08): L1 objective on the scaled target,
deterministic, one thread, a fixed seed and no bagging, so the same data always gives the same
model (FR-018, SC-005)."""

from typing import Any

import lightgbm as lgb
import numpy as np

from brain.config import Settings
from brain.forecasting.features import CATEGORICAL, FEATURES


def params(settings: Settings) -> dict[str, Any]:
    return {
        "objective": "l1",
        "num_leaves": settings.lgbm_num_leaves,
        "min_data_in_leaf": settings.lgbm_min_data_in_leaf,
        "learning_rate": settings.lgbm_learning_rate,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 1,
        "seed": settings.lgbm_seed,
        "bagging_fraction": 1.0,
        "bagging_freq": 0,
        "feature_fraction": 1.0,
        "verbose": -1,
    }


def train(X: np.ndarray, y: np.ndarray, settings: Settings) -> lgb.Booster:
    dataset = lgb.Dataset(
        X, label=y, feature_name=FEATURES, categorical_feature=CATEGORICAL, free_raw_data=False
    )
    return lgb.train(params(settings), dataset, num_boost_round=settings.lgbm_num_boost_round)


def predict(booster: lgb.Booster, X: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return np.maximum(booster.predict(X) * scale, 0.0)
