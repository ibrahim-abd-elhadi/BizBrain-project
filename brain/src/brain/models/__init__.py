"""brain_db tables (feature 003 data-model.md). Importing this package registers every model on
Base.metadata (Alembic and `brain-worker reset` rely on it)."""

from brain.models.anomaly import Anomaly
from brain.models.anomaly_scan_progress import AnomalyScanProgress
from brain.models.base import Base
from brain.models.forecast import Forecast
from brain.models.forecast_evaluation import ForecastEvaluation
from brain.models.job_run import JobRun
from brain.models.model_artifact import ModelArtifact
from brain.models.model_choice import ModelChoice
from brain.models.model_health import ModelHealth
from brain.models.poll_state import PollState
from brain.models.product_ref import ProductRef
from brain.models.proposal import Proposal
from brain.models.proposal_attempt import ProposalAttempt
from brain.models.proposal_line import ProposalLine
from brain.models.proposal_live_product import ProposalLiveProduct
from brain.models.risk_result import RiskResult
from brain.models.sales_daily import SalesDaily

__all__ = [
    "Anomaly",
    "AnomalyScanProgress",
    "Base",
    "Forecast",
    "ForecastEvaluation",
    "JobRun",
    "ModelArtifact",
    "ModelChoice",
    "ModelHealth",
    "PollState",
    "ProductRef",
    "Proposal",
    "ProposalAttempt",
    "ProposalLine",
    "ProposalLiveProduct",
    "RiskResult",
    "SalesDaily",
]
