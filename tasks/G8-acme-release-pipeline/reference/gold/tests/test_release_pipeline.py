import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _stage_temp_repo(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "releases", ".git"))
    # Exclude pipeline recursion test from nested repo copy so build_release runs service tests cleanly
    for p in list((dst / "tests").glob("test_release_*.py")):
        p.unlink()
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@local",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@local",
    }
    subprocess.run(["git", "init", "-q"], cwd=str(dst), env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(dst), env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(dst), env=env, check=True)


def test_release_pipeline_builds_verified_bundle(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    repo = tmp_path / "repo_ok"
    _stage_temp_repo(root, repo)
    out = tmp_path / "bundle"
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "build_release.py"), "--out", str(out)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads((out / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["bundle_format"] == "acme-rel-1"
    assert manifest["rollback_verified"] is True
    assert manifest["built_at_utc"].endswith("Z")
    assert "  release-manifest.json\n" in (out / "MANIFEST.sha256").read_text(encoding="utf-8")


def test_pipeline_aborts_before_manifest_when_down_migration_missing(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    copy_ws = tmp_path / "repo_bad"
    _stage_temp_repo(root, copy_ws)
    (copy_ws / "migrations" / "002_add_settlement_index.down.sql").unlink()
    out = tmp_path / "aborted_bundle"
    proc = subprocess.run(
        [sys.executable, str(copy_ws / "scripts" / "build_release.py"), "--out", str(out)],
        cwd=str(copy_ws),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert not (out / "release-manifest.json").exists()


def test_pipeline_aborts_when_down_migration_sql_fails(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    copy_ws = tmp_path / "repo_broken_down"
    _stage_temp_repo(root, copy_ws)
    (copy_ws / "migrations" / "003_add_settlement_batches.down.sql").write_text(
        "DROP TABLE nonexistent_settlement_table;\n", encoding="utf-8"
    )
    out = tmp_path / "aborted_broken_down"
    proc = subprocess.run(
        [sys.executable, str(copy_ws / "scripts" / "build_release.py"), "--out", str(out)],
        cwd=str(copy_ws),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert not (out / "release-manifest.json").exists()
