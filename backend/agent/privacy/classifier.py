"""Local RED/YELLOW/GREEN data classifier."""

from enum import Enum
import re

from agent.privacy.scrubber import PrivacyScrubber


class DataClass(Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


RED_PATTERNS = (
    (re.compile(r"\b(?:api[_ -]?key|secret|password|token)\b\s*[:=]", re.I), "Secret material detected."),
    (re.compile(r"\b(?:seed phrase|private key)\b", re.I), "Wallet or private-key material detected."),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "Government identifier pattern detected."),
)

RED_LABELS = {"SECRET", "CRYPTO_KEY", "GOVERNMENT_ID", "CREDIT_CARD", "FINANCIAL_ID"}


def classify(text: str) -> tuple[DataClass, str]:
    value = text or ""
    for pattern, reason in RED_PATTERNS:
        if pattern.search(value):
            return DataClass.RED, reason

    detections = PrivacyScrubber().analyze(value)
    if not detections:
        return DataClass.GREEN, "No sensitive data detected."

    red = next((item for item in detections if item.label in RED_LABELS), None)
    if red is not None:
        return DataClass.RED, f"{red.label.replace('_', ' ').title()} detected."

    labels = sorted({item.label.replace("_", " ").title() for item in detections})
    return DataClass.YELLOW, f"PII detected: {', '.join(labels)}."
