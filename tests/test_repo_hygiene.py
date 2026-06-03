from __future__ import annotations

import subprocess
from pathlib import Path

from alphadb.repo_hygiene import audit_repository, main


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def git_add(path: Path, *files: str) -> None:
    subprocess.run(["git", "add", *files], cwd=path, check=True)


def test_hygiene_blocks_tracked_artifacts_and_model_binaries(tmp_path: Path) -> None:
    init_repo(tmp_path)
    artifact = tmp_path / "artifacts" / "models" / "model.joblib"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"model")
    git_add(tmp_path, str(artifact.relative_to(tmp_path)))

    report = audit_repository(tmp_path)

    assert not report.ok()
    assert any(finding.rule == "artifact-tree" for finding in report.tracked_findings)


def test_hygiene_blocks_tracked_secret_assignment(tmp_path: Path) -> None:
    init_repo(tmp_path)
    config = tmp_path / "public-config.env"
    config.write_text(
        "KALSHI_API_KEY_ID=real-looking-key-value\n"
        "ALPHADB_X_BEARER_TOKEN=real-looking-x-token\n",
        encoding="utf-8",
    )
    git_add(tmp_path, config.name)

    report = audit_repository(tmp_path)

    assert not report.ok()
    assert any(finding.rule == "secret-assignment" for finding in report.tracked_findings)


def test_hygiene_allows_placeholder_secret_examples(tmp_path: Path) -> None:
    init_repo(tmp_path)
    example = tmp_path / ".env.example"
    example.write_text(
        "KALSHI_API_KEY_ID=\n"
        "ALPHADB_DASHBOARD_COOKIE_SECRET=<Secrets Manager value>\n",
        encoding="utf-8",
    )
    git_add(tmp_path, example.name)

    report = audit_repository(tmp_path)

    assert report.ok()
    assert report.tracked_findings == ()


def test_audit_warns_for_ignored_local_private_material(tmp_path: Path) -> None:
    init_repo(tmp_path)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".env\nartifacts/\n*.pem\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("# public\n", encoding="utf-8")
    git_add(tmp_path, gitignore.name, readme.name)

    (tmp_path / ".env").write_text("KALSHI_API_KEY_ID=local-only\n", encoding="utf-8")
    key = tmp_path / "private_key.pem"
    key.write_text("not a real key\n", encoding="utf-8")
    artifact = tmp_path / "artifacts" / "strategy-manager" / "run.log"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("local log\n", encoding="utf-8")

    report = audit_repository(tmp_path)

    assert report.ok()
    assert not report.ok(strict_local=True)
    assert {finding.rule for finding in report.local_findings} >= {
        "environment-file",
        "private-key-file",
        "artifact-tree",
    }


def test_cli_check_and_audit_exit_codes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# public\n", encoding="utf-8")
    git_add(tmp_path, readme.name)

    assert main(["check", "--repo", str(tmp_path)]) == 0
    assert main(["audit", "--repo", str(tmp_path)]) == 0

    model = tmp_path / "model.joblib"
    model.write_bytes(b"model")
    git_add(tmp_path, model.name)

    assert main(["check", "--repo", str(tmp_path)]) == 1
