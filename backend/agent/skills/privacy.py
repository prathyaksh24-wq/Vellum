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
_PUBLIC_RUNTIME_PATH = re.compile(r"^/mnt/user-data/(?:outputs|uploads)(?:/|$)", re.I)
_PORTABLE_CODE_PATH = re.compile(
    r"^(?:/tmp(?:/|$)|/(?:usr/)?bin/(?:env|bash|sh|python\d*)$|/dev/null$|/\{[^}]+\})",
    re.I,
)


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

    def validate_generated(
        self,
        files: Iterable[tuple[str, str]],
        *,
        protected_values: Iterable[str] = (),
        public_package: bool = False,
    ) -> None:
        protected = [value for value in protected_values if value]
        for path, content in files:
            self.sanitize(content)
            findings = [] if public_package else [
                item
                for item in self.scrubber.analyze(content)
                if item.label not in {"ORGANIZATION"}
                and not (item.label == "PERSON" and content[content.rfind("\n", 0, item.start) + 1 : item.start].lstrip().startswith("#"))
                and (item.label != "PERSON" or item.source == "regex" or item.score >= 0.9)
            ]
            rules = []
            if self._contains_private_path(content, public_package=public_package):
                rules.append("private_path")
            rules.extend(
                label
                for label, pattern in (
                    ("credential_url", _CREDENTIAL_URL),
                    *(() if public_package else (("private_handle", _HANDLE),)),
                    ("secret", _SECRET),
                    ("prompt_injection", _INJECTION),
                )
                if pattern.search(content)
            )
            if findings:
                rules.extend(sorted({f"pii_{item.label.casefold()}" for item in findings}))
            if any(value in content for value in protected):
                rules.append("protected_source_value")
            if rules:
                raise SkillPrivacyError(
                    f"generated skill file failed privacy validation: {path} ({', '.join(dict.fromkeys(rules))})"
                )

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

    @staticmethod
    def _contains_private_path(text: str, *, public_package: bool) -> bool:
        public_url_spans = [(match.start(), match.end()) for match in _PUBLIC_URL.finditer(text)]
        for match in _PATHS.finditer(text):
            value = match.group(0).strip("'\"`),.;:")
            if public_package:
                if any(match.start() < end and start < match.end() for start, end in public_url_spans):
                    continue
                if _PUBLIC_RUNTIME_PATH.match(value) or _PORTABLE_CODE_PATH.match(value):
                    continue
            return True
        return False
