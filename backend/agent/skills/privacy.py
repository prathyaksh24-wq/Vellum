from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import unicodedata
from typing import Iterable

from agent.obsidian.folder_policy import can_send_to_llm
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber


class SkillPrivacyError(ValueError):
    pass


_PATHS = re.compile(r"(?:[A-Za-z]:\\|\\\\[^\s\\]+\\|(?<![:\w])/(?:[^/\s]+/)*[^/\s]+|~/|\$\{?[A-Z_][A-Z0-9_]*\}?|%[A-Z_][A-Z0-9_]*%)\S*", re.I)
_CREDENTIAL_URL = re.compile(r"https?://[^\s/:]+:[^\s/@]+@[^\s]+", re.I)
_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,32}\b")
_SECRET = re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])[-_A-Za-z0-9]{16,}\b", re.I)
_INJECTION = re.compile(r"(?:ignore|override).{0,30}(?:instructions|privacy)|reproduce.{0,30}(?:private|secret|source)", re.I | re.S)
_PUBLIC_URL = re.compile(r"https?://(?![^\s/@]+:[^\s/@]+@)[^\s)\]>]+", re.I)


@dataclass(frozen=True)
class PrivacyGateResult:
    text: str
    classification: str
    replacements: int


class SkillPrivacyGate:
    """Local-only privacy boundary for skill learning, history, and hub search."""

    def __init__(self):
        self.scrubber = PrivacyScrubber()

    def sanitize(self, text: str, *, source_path: str | Path | None = None) -> PrivacyGateResult:
        value = unicodedata.normalize("NFKC", text or "")
        value = "".join(character for character in value if unicodedata.category(character) != "Cf")
        classification, _reason = classify(value)
        if classification is DataClass.RED:
            raise SkillPrivacyError("RED content cannot be used as a skill signal")
        if source_path is not None and not can_send_to_llm(str(source_path)):
            raise SkillPrivacyError("folder policy blocks this source from skill authoring")
        if _INJECTION.search(value):
            raise SkillPrivacyError("skill-authoring prompt injection detected")
        public_urls: list[str] = []

        def preserve_url(match: re.Match) -> str:
            public_urls.append(match.group(0))
            return f"PUBLICURLTOKEN{len(public_urls) - 1}"

        protected_value = _PUBLIC_URL.sub(preserve_url, value)
        clean, replacements = self.scrubber.scrub(protected_value)
        clean = _PATHS.sub("[PATH]", clean)
        clean = _CREDENTIAL_URL.sub("[CREDENTIAL_URL]", clean)
        clean = _HANDLE.sub("[HANDLE]", clean)
        clean = _SECRET.sub("[SECRET]", clean)
        for index, url in enumerate(public_urls):
            clean = clean.replace(f"PUBLICURLTOKEN{index}", url)
        if self._high_entropy_tokens(clean):
            raise SkillPrivacyError("high-entropy secret-like content detected")
        return PrivacyGateResult(clean, classification.value, len(replacements))

    def validate_generated(self, files: Iterable[tuple[str, str]], *, protected_values: Iterable[str] = ()) -> None:
        protected = [value for value in protected_values if value]
        for path, content in files:
            self.sanitize(content)
            findings = [
                item
                for item in self.scrubber.analyze(content)
                if item.label not in {"ORGANIZATION"}
                and not (item.label == "PERSON" and content[content.rfind("\n", 0, item.start) + 1 : item.start].lstrip().startswith("#"))
                and (item.label != "PERSON" or item.source == "regex" or item.score >= 0.9)
            ]
            deterministic = any(pattern.search(content) for pattern in (_PATHS, _CREDENTIAL_URL, _HANDLE, _SECRET, _INJECTION))
            if findings or deterministic or any(value in content for value in protected):
                raise SkillPrivacyError(f"generated skill file failed privacy validation: {path}")

    @staticmethod
    def marketplace_query(text: str) -> str:
        return SkillPrivacyGate().sanitize(text).text

    @staticmethod
    def _high_entropy_tokens(text: str) -> bool:
        for token in re.findall(r"[A-Za-z0-9+/=_-]{32,}", text):
            counts = {character: token.count(character) for character in set(token)}
            entropy = -sum((count / len(token)) * math.log2(count / len(token)) for count in counts.values())
            if entropy >= 4.3:
                return True
        return False
