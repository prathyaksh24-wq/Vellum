from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass(frozen=True)
class SkillSecurityFinding:
    pattern_id: str
    severity: str
    category: str
    description: str
    path: str


@dataclass
class SkillSecurityResult:
    skill_name: str
    source: str
    trust_level: str
    verdict: str
    findings: list[SkillSecurityFinding] = field(default_factory=list)


_PATTERNS = [
    (
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions|reveal\s+(?:the\s+)?system\s+prompt", re.I),
        "prompt_injection",
        "critical",
        "injection",
        "attempts to override or reveal system instructions",
    ),
    (
        re.compile(r"(?:curl|wget)[^\n]*(?:\$[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)|%[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)%)", re.I),
        "secret_exfiltration",
        "critical",
        "exfiltration",
        "sends a secret-like environment variable over the network",
    ),
    (
        re.compile(r"rm\s+-rf\s+(?:/|~|\$HOME)(?:\s|$)", re.I),
        "destructive_remove",
        "critical",
        "destructive",
        "recursively deletes a root or home directory",
    ),
    (
        re.compile(r"(?:curl|wget)[^\n|]*\|\s*(?:ba)?sh\b", re.I),
        "download_pipe_shell",
        "critical",
        "supply_chain",
        "downloads content directly into a shell",
    ),
    (
        re.compile(r"\bos\.(?:system|popen)\s*\(", re.I),
        "unguarded_shell",
        "high",
        "execution",
        "uses unguarded shell execution",
    ),
    (
        re.compile(r"(?:powershell|pwsh)[^\n]*(?:-enc(?:odedcommand)?\b|frombase64string)|base64\s+-d[^\n]*\|\s*(?:ba)?sh", re.I),
        "encoded_execution",
        "critical",
        "execution",
        "decodes or executes an encoded payload",
    ),
    (
        re.compile(r"(?:chmod\s+777|sudo\s+(?:rm|sh|bash)|Invoke-Expression\b|\beval\s*\()", re.I),
        "unsafe_shell",
        "high",
        "execution",
        "contains an unsafe shell execution pattern",
    ),
]
_INVISIBLE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}


class SkillSecurityScanner:
    def __init__(self, *, max_file_bytes: int = 512_000, max_package_bytes: int = 4_000_000):
        self.max_file_bytes = max_file_bytes
        self.max_package_bytes = max_package_bytes

    def scan(self, root: str | Path, *, source: str, trust_level: str) -> SkillSecurityResult:
        package_root = Path(root)
        findings: list[SkillSecurityFinding] = []
        total = 0
        if not (package_root / "SKILL.md").is_file():
            findings.append(self._finding("missing_skill", "critical", "structure", "package has no SKILL.md", "SKILL.md"))
        for path in package_root.rglob("*"):
            relative = path.relative_to(package_root).as_posix()
            if path.is_symlink():
                findings.append(self._finding("symlink", "critical", "structure", "package contains a symlink", relative))
                continue
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            if size > self.max_file_bytes:
                findings.append(self._finding("oversized_file", "high", "structure", "file exceeds size limit", relative))
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append(self._finding("binary_file", "high", "structure", "unexpected binary file", relative))
                continue
            for regex, pattern_id, severity, category, description in _PATTERNS:
                if regex.search(text):
                    findings.append(self._finding(pattern_id, severity, category, description, relative))
            if any(character in text for character in _INVISIBLE):
                findings.append(
                    self._finding(
                        "invisible_unicode",
                        "high",
                        "injection",
                        "contains invisible Unicode characters",
                        relative,
                    )
                )
        if total > self.max_package_bytes:
            findings.append(self._finding("oversized_package", "critical", "structure", "package exceeds size limit", "."))
        verdict = self._verdict(findings)
        return SkillSecurityResult(
            skill_name=package_root.name,
            source=source,
            trust_level=trust_level,
            verdict=verdict,
            findings=findings,
        )

    @staticmethod
    def _finding(pattern_id: str, severity: str, category: str, description: str, path: str) -> SkillSecurityFinding:
        return SkillSecurityFinding(pattern_id, severity, category, description, path)

    @staticmethod
    def _verdict(findings: list[SkillSecurityFinding]) -> str:
        if any(finding.severity == "critical" for finding in findings):
            return "dangerous"
        if findings:
            return "caution"
        return "safe"


def allow_skill_install(result: SkillSecurityResult, *, force: bool = False) -> tuple[bool, str]:
    if result.verdict == "dangerous":
        return False, "dangerous verdict cannot be overridden"
    if result.verdict == "caution" and result.trust_level == "community":
        if force:
            return True, "forced caution"
        return False, "community caution requires force"
    return True, "allowed"
