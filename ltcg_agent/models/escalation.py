from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class EscalationSeverity(StrEnum):
    WARNING = "WARNING"
    ESCALATE = "ESCALATE"


class EscalationReason(StrEnum):
    RSU_ESPP_DETECTED = "RSU_ESPP_DETECTED"
    RESIDENCY_UNCONFIRMED = "RESIDENCY_UNCONFIRMED"
    DUPLICATE_LOT_RISK = "DUPLICATE_LOT_RISK"
    FOREIGN_TAX_CREDIT = "FOREIGN_TAX_CREDIT"
    DIVIDEND_INCOME = "DIVIDEND_INCOME"
    PRE_2000_LOT = "PRE_2000_LOT"


class EscalationFlag(BaseModel):
    reason: EscalationReason
    severity: EscalationSeverity
    detail: str

    model_config = {"frozen": True}
