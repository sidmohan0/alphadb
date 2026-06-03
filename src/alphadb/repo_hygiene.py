"""Repository hygiene checks for public AlphaDB sharing."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

FindingSeverity = Literal["error", "warning"]

MODEL_BINARY_SUFFIXES = {
    ".cbm",
    ".h5",
    ".joblib",
    ".onnx",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".xgb",
}
DATASET_SUFFIXES = {".db", ".parquet", ".sqlite", ".sqlite3"}
PRIVATE_KEY_SUFFIXES = {".key", ".pem"}
SECRET_ASSIGNMENT_RE = re.compile(
    r"^\s*"
    r"(?P<key>"
    r"AWS_SECRET_ACCESS_KEY|"
    r"AWS_SESSION_TOKEN|"
    r"DATABENTO_API_KEY|"
    r"X_BEARER_TOKEN|"
    r"ALPHADB_X_BEARER_TOKEN|"
    r"KALSHI_API_KEY_ID|"
    r"KALSHI_PRIVATE_KEY|"
    r"ALPHADB_DASHBOARD_COOKIE_SECRET"
    r")"
    r"[ \t]*[:=][ \t]*(?P<value>[^#\n]+)",
    re.MULTILINE,
)
PRIVATE_KEY_BLOCK_RE = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
MAX_TEXT_SCAN_BYTES = 1_000_000
LOCAL_SCAN_SKIP_PREFIXES = (
    ".git/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".venv/",
    "__pycache__/",
)


@dataclass(frozen=True)
class HygieneFinding:
    severity: FindingSeverity
    scope: Literal["tracked", "local"]
    path: str
    rule: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "scope": self.scope,
            "path": self.path,
            "rule": self.rule,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class HygieneReport:
    repo_root: Path
    tracked_findings: tuple[HygieneFinding, ...]
    local_findings: tuple[HygieneFinding, ...]

    def ok(self, *, strict_local: bool = False) -> bool:
        if self.tracked_findings:
            return False
        return not (strict_local and self.local_findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo_root": str(self.repo_root),
            "tracked_findings": [finding.as_dict() for finding in self.tracked_findings],
            "local_findings": [finding.as_dict() for finding in self.local_findings],
            "tracked_blocker_count": len(self.tracked_findings),
            "local_warning_count": len(self.local_findings),
        }


def audit_repository(path: str | Path = ".") -> HygieneReport:
    repo_root = discover_repo_root(path)
    tracked_findings = tuple(find_tracked_findings(repo_root))
    local_findings = tuple(find_local_findings(repo_root))
    return HygieneReport(
        repo_root=repo_root,
        tracked_findings=tracked_findings,
        local_findings=local_findings,
    )


def discover_repo_root(path: str | Path) -> Path:
    result = run_git(Path(path), "rev-parse", "--show-toplevel", text=True)
    return Path(str(result.stdout).strip()).resolve()


def find_tracked_findings(repo_root: Path) -> list[HygieneFinding]:
    findings: list[HygieneFinding] = []
    for path in git_path_list(repo_root, "ls-files", "-z"):
        path_finding = classify_risky_path(path, scope="tracked", severity="error")
        if path_finding is not None:
            findings.append(path_finding)
        findings.extend(scan_tracked_file_content(repo_root, path))
    return findings


def find_local_findings(repo_root: Path) -> list[HygieneFinding]:
    findings: list[HygieneFinding] = []
    local_paths = {
        *git_path_list(repo_root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
        *git_path_list(repo_root, "ls-files", "--others", "--exclude-standard", "-z"),
    }
    for path in sorted(local_paths):
        if should_skip_local_path(path):
            continue
        path_finding = classify_risky_path(path, scope="local", severity="warning")
        if path_finding is not None:
            findings.append(path_finding)
    return findings


def should_skip_local_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in LOCAL_SCAN_SKIP_PREFIXES)


def classify_risky_path(
    path: str,
    *,
    scope: Literal["tracked", "local"],
    severity: FindingSeverity,
) -> HygieneFinding | None:
    normalized = path.replace("\\", "/")
    lowered = normalized.lower()
    name = Path(normalized).name.lower()
    suffix = Path(normalized).suffix.lower()
    parts = lowered.split("/")

    rule_detail: tuple[str, str] | None = None
    if name == ".env.example":
        return None
    if name == ".env" or name.startswith(".env."):
        rule_detail = ("environment-file", "environment files can contain live secrets")
    elif lowered.startswith("artifacts/"):
        rule_detail = ("artifact-tree", "artifacts belong outside public Git")
    elif lowered.startswith("data/") or lowered.startswith("research/"):
        rule_detail = ("generated-data-tree", "generated data and research outputs stay out of Git")
    elif any(part.endswith(".egg-info") for part in parts):
        rule_detail = ("build-metadata", "generated package metadata should not be committed")
    elif suffix in PRIVATE_KEY_SUFFIXES:
        rule_detail = ("private-key-file", "private key files must never be committed")
    elif suffix in MODEL_BINARY_SUFFIXES:
        rule_detail = ("model-binary", "model binaries should be referenced by artifact metadata")
    elif suffix in DATASET_SUFFIXES:
        rule_detail = ("generated-dataset", "generated datasets and local databases stay out of Git")
    elif suffix == ".log" and ("strategy" in lowered or "runtime" in lowered):
        rule_detail = ("strategy-log", "strategy and runtime logs can reveal private operations")

    if rule_detail is None:
        return None
    rule, detail = rule_detail
    return HygieneFinding(
        severity=severity,
        scope=scope,
        path=normalized,
        rule=rule,
        detail=detail,
    )


def scan_tracked_file_content(repo_root: Path, path: str) -> list[HygieneFinding]:
    full_path = repo_root / path
    try:
        payload = full_path.read_bytes()
    except OSError:
        return []
    if len(payload) > MAX_TEXT_SCAN_BYTES:
        return []

    findings: list[HygieneFinding] = []
    if PRIVATE_KEY_BLOCK_RE.search(payload):
        findings.append(
            HygieneFinding(
                severity="error",
                scope="tracked",
                path=path,
                rule="private-key-material",
                detail="tracked file contains a private-key block",
            )
        )

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return findings

    for match in SECRET_ASSIGNMENT_RE.finditer(text):
        key = match.group("key")
        value = normalize_assignment_value(match.group("value"))
        if assignment_value_is_placeholder(value):
            continue
        findings.append(
            HygieneFinding(
                severity="error",
                scope="tracked",
                path=path,
                rule="secret-assignment",
                detail=f"tracked file assigns a non-placeholder value to {key}",
            )
        )
    return findings


def normalize_assignment_value(value: str) -> str:
    value = value.strip()
    if value.endswith("\\"):
        value = value[:-1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def assignment_value_is_placeholder(value: str) -> bool:
    lowered = value.lower()
    if value in {"", "..."}:
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    if "$(" in value or "${" in value:
        return True
    return lowered in {"changeme", "example", "placeholder", "replace-me", "test"}


def git_path_list(repo_root: Path, *args: str) -> list[str]:
    result = run_git(repo_root, *args)
    if not result.stdout:
        return []
    return [
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
    ]


def run_git(cwd: Path, *args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=text,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-repo-hygiene")
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="Fail if tracked public Git state has blockers")
    check.add_argument("--repo", default=".")
    check.add_argument("--json", action="store_true")

    audit = subparsers.add_parser(
        "audit",
        help="Report tracked blockers and ignored or untracked local sensitive files",
    )
    audit.add_argument("--repo", default=".")
    audit.add_argument("--json", action="store_true")
    audit.add_argument(
        "--strict-local",
        action="store_true",
        help="Also fail when ignored or untracked local sensitive files are present",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "check"
    report = audit_repository(args.repo)
    strict_local = bool(getattr(args, "strict_local", False))

    if bool(getattr(args, "json", False)):
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(format_report(report, command=command, strict_local=strict_local))

    return 0 if report.ok(strict_local=strict_local) else 1


def format_report(report: HygieneReport, *, command: str, strict_local: bool = False) -> str:
    lines = [
        f"AlphaDB repository hygiene {command}",
        f"repo: {report.repo_root}",
        "",
    ]
    lines.extend(format_findings("Tracked blockers", report.tracked_findings))
    if command == "audit":
        lines.append("")
        lines.extend(format_findings("Local ignored/untracked warnings", report.local_findings))
    elif report.local_findings:
        lines.append("")
        lines.append(
            f"Local ignored/untracked warnings: {len(report.local_findings)} "
            "(run `alphadb-repo-hygiene audit` for details)"
        )
    lines.append("")
    if report.ok(strict_local=strict_local):
        if report.local_findings and not strict_local:
            lines.append("status: pass for public Git state; local warnings are present")
        else:
            lines.append("status: pass")
    else:
        lines.append("status: fail")
    return "\n".join(lines)


def format_findings(title: str, findings: Sequence[HygieneFinding], *, limit: int = 20) -> list[str]:
    if not findings:
        return [f"{title}: none"]
    lines = [f"{title}: {len(findings)}"]
    for finding in findings[:limit]:
        lines.append(f"- {finding.path} [{finding.rule}]: {finding.detail}")
    remaining = len(findings) - limit
    if remaining > 0:
        lines.append(f"- ... {remaining} more")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
