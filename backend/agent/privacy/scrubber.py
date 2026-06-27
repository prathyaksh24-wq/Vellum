"""Local PII detection and scrubbing before any future cloud boundary."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Replacement:
    label: str
    value: str
    token: str


@dataclass(frozen=True)
class PIIDetection:
    label: str
    value: str
    start: int
    end: int
    score: float = 1.0
    source: str = "regex"


_LABEL_PRIORITY = {
    "SECRET": 100,
    "CRYPTO_KEY": 95,
    "GOVERNMENT_ID": 90,
    "CREDIT_CARD": 85,
    "ADDRESS": 75,
    "EMAIL": 70,
    "PHONE": 65,
    "ORGANIZATION": 60,
    "PERSON": 55,
    "LOCATION": 50,
    "NETWORK_ID": 45,
    "FINANCIAL_ID": 45,
}

_ENTITY_LABELS = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "US_SSN": "GOVERNMENT_ID",
    "US_PASSPORT": "GOVERNMENT_ID",
    "US_DRIVER_LICENSE": "GOVERNMENT_ID",
    "IN_PAN": "GOVERNMENT_ID",
    "IN_AADHAAR": "GOVERNMENT_ID",
    "CREDIT_CARD": "CREDIT_CARD",
    "CRYPTO": "CRYPTO_KEY",
    "IBAN_CODE": "FINANCIAL_ID",
    "US_BANK_NUMBER": "FINANCIAL_ID",
    "IP_ADDRESS": "NETWORK_ID",
    "PERSON": "PERSON",
    "LOCATION": "LOCATION",
    "ORGANIZATION": "ORGANIZATION",
}

_NAME_STOPWORDS = {
    "Agent",
    "Amazon",
    "April",
    "August",
    "Books",
    "Contact",
    "December",
    "February",
    "Friday",
    "January",
    "July",
    "June",
    "March",
    "Monday",
    "November",
    "October",
    "Saturday",
    "September",
    "Sports",
    "Sunday",
    "Thursday",
    "Tuesday",
    "Wednesday",
}


class PrivacyScrubber:
    regex_patterns = (
        ("SECRET", re.compile(r"\b(?:api[_ -]?key|secret|password|token)\b\s*[:=]\s*\S+", re.I), 1.0),
        ("CRYPTO_KEY", re.compile(r"\b(?:seed phrase|private key)\b\s*[:=]?\s*(?:\S+\s*){3,24}", re.I), 1.0),
        ("EMAIL", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), 0.95),
        ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b"), 0.85),
        ("PHONE", re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{8,}\d)\b"), 0.85),
        ("GOVERNMENT_ID", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), 0.95),
        ("GOVERNMENT_ID", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), 0.9),
        ("GOVERNMENT_ID", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0.9),
        (
            "GOVERNMENT_ID",
            re.compile(
                r"\b(?:passport|driver'?s license|aadhaar|pan|ssn|social security|tax id|employee id|account(?: number)?)\b\s*[:#-]?\s*[A-Z0-9-]{4,}\b",
                re.I,
            ),
            0.9,
        ),
        (
            "ADDRESS",
            re.compile(
                r"\b\d{1,6}[A-Za-z]?\s+[A-Za-z0-9 ,'-]{2,80}\s+(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|blvd|way|court|ct|circle|cir|place|pl|terrace|ter|road)\b(?:[, ]+[A-Za-z .'-]+){0,3}(?:\s+\d{5}(?:-\d{4})?)?",
                re.I,
            ),
            0.8,
        ),
        (
            "ADDRESS",
            re.compile(
                r"\b(?:flat|apt|apartment|suite|unit|house)\s*[A-Z0-9-]+[, ]+[A-Za-z0-9 .,'-]{2,80}\s+(?:road|rd|street|st|lane|ln|avenue|ave)\b",
                re.I,
            ),
            0.8,
        ),
        (
            "ORGANIZATION",
            re.compile(
                r"\b[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,5}\s+(?:Inc|LLC|Ltd|Limited|Corp|Corporation|Company|Co|University|College|Bank|Labs|Technologies|Systems)\b\.?",
            ),
            0.75,
        ),
        (
            "PERSON",
            re.compile(r"\b(?!Agent\b|Amazon\b|Books\b|Contact\b|Email\b|Call\b|Meet\b|Message\b|Sports\b)[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b"),
            0.65,
        ),
    )

    def analyze(self, text: str) -> list[PIIDetection]:
        value = text or ""
        if not value:
            return []

        detections = [*self._presidio_detections(value), *self._regex_detections(value)]
        return _select_non_overlapping(detections)

    def scrub(self, text: str) -> tuple[str, list[Replacement]]:
        clean = text or ""
        detections = self.analyze(clean)
        replacements: list[Replacement] = []
        label_counts: dict[str, int] = {}

        tokens_by_span: dict[tuple[int, int], str] = {}
        for detection in detections:
            label_counts[detection.label] = label_counts.get(detection.label, 0) + 1
            token = f"[{detection.label}_{label_counts[detection.label]}]"
            replacements.append(Replacement(detection.label, detection.value, token))
            tokens_by_span[(detection.start, detection.end)] = token

        for detection in sorted(detections, key=lambda item: item.start, reverse=True):
            token = tokens_by_span[(detection.start, detection.end)]
            clean = f"{clean[:detection.start]}{token}{clean[detection.end:]}"

        return clean, replacements

    def _regex_detections(self, text: str) -> list[PIIDetection]:
        detections: list[PIIDetection] = []
        for label, pattern, score in self.regex_patterns:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                if not value or (label == "PERSON" and _looks_like_false_name(value)):
                    continue
                detections.append(
                    PIIDetection(
                        label=label,
                        value=value,
                        start=match.start(),
                        end=match.end(),
                        score=score,
                    )
                )
        return detections

    def _presidio_detections(self, text: str) -> list[PIIDetection]:
        analyzer = _get_presidio_analyzer()
        if analyzer is None:
            return []
        try:
            results = analyzer.analyze(text=text, language="en", score_threshold=0.45)
        except Exception as exc:
            logger.debug("Presidio analysis skipped: %s", exc)
            return []

        detections: list[PIIDetection] = []
        for result in results:
            entity_type = getattr(result, "entity_type", "")
            label = _ENTITY_LABELS.get(str(entity_type), str(entity_type) or "PII")
            start = int(getattr(result, "start", 0))
            end = int(getattr(result, "end", 0))
            if start >= end:
                continue
            detections.append(
                PIIDetection(
                    label=label,
                    value=text[start:end],
                    start=start,
                    end=end,
                    score=float(getattr(result, "score", 0.0) or 0.0),
                    source="presidio",
                )
            )
        return detections


@lru_cache(maxsize=1)
def _get_presidio_analyzer():
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError:
        return None

    nlp_configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
    }
    try:
        provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
        return AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    except Exception as exc:
        logger.warning("Presidio unavailable; using deterministic regex PII fallback: %s", exc)
        return None


def _select_non_overlapping(detections: list[PIIDetection]) -> list[PIIDetection]:
    ranked = sorted(
        detections,
        key=lambda item: (
            -_LABEL_PRIORITY.get(item.label, 0),
            -(item.end - item.start),
            -item.score,
            item.start,
        ),
    )
    selected: list[PIIDetection] = []
    occupied: list[range] = []
    for detection in ranked:
        span = range(detection.start, detection.end)
        if any(_overlaps(span, existing) for existing in occupied):
            continue
        selected.append(detection)
        occupied.append(span)
    return sorted(selected, key=lambda item: item.start)


def _overlaps(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop


def _looks_like_false_name(value: str) -> bool:
    words = value.split()
    return any(word in _NAME_STOPWORDS for word in words)
