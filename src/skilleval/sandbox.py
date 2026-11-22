"""Docker sandbox orchestration with strict host isolation and Claude OAuth volume."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skilleval.config import load_study_spec, render_user_prompt, sha256_file, sha256_text
from skilleval.schemas import MatrixRow


@dataclass
class ContainerRunOutput:
    exit_code: int
    agent_seconds: float
    timed_out: bool
    docker_image_id: str | None
    prompt_sha256: str
    preload_sha256: str | None
    stderr_text: str


def docker_image_id(image: str) -> str | None:
    proc = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def build_sandbox_image(root: Path, tag: str | None = None) -> str:
    spec = load_study_spec(root)
    image = tag or os.environ.get("SKILLEVAL_DOCKER_IMAGE") or spec["runtime"]["docker_image"]
    dockerfile = root / "docker" / "Dockerfile.base"
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Missing Dockerfile: {dockerfile}")
    subprocess.run(
        ["docker", "build", "-f", str(dockerfile), "-t", image, str(root / "docker")],
        check=True,
    )
    img_id = docker_image_id(image)
    if not img_id:
        raise RuntimeError(f"Built image '{image}' but could not read its image ID.")
    return img_id


def login_claude_volume(root: Path) -> None:
    """Open an interactive container attached ONLY to the dedicated Claude OAuth volume."""
    spec = load_study_spec(root)
    image = os.environ.get("SKILLEVAL_DOCKER_IMAGE") or spec["runtime"]["docker_image"]
    volume = os.environ.get("SKILLEVAL_CLAUDE_AUTH_VOLUME") or spec["runtime"]["auth_volume"]
    subprocess.run(["docker", "volume", "create", volume], check=True)
    print(
        f"Opening interactive Claude login inside volume '{volume}'. "
        "Complete login, then type `exit`."
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-it",
            "-v",
            f"{volume}:/claude-auth",
            "-e",
            "CLAUDE_CONFIG_DIR=/claude-auth",
            image,
            "claude",
            "login",
        ],
        check=True,
    )


def _build_claude_settings(row: MatrixRow) -> dict[str, Any]:
    """Generate strict per-run Claude Code settings + Pre/PostToolUse capture hooks."""
    tools = ["Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "Bash"]
    if row.condition in ("B", "C1"):
        tools.append("Skill")

    deny = ["Agent", "Task", "WebSearch", "WebFetch", "NotebookEdit"]
    if row.condition in ("A", "C2"):
        deny.append("Skill")

    hook_cmd = "python3 /control/capture_hook.py /capture/hook-events.jsonl"
    hooks = {
        "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": hook_cmd}]}],
        "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": hook_cmd}]}],
    }

    return {
        "permissions": {"defaultMode": "dontAsk", "allow": tools, "deny": deny},
        "disableBundledSkills": True,
        "disableClaudeAiConnectors": True,
        "hooks": hooks,
    }


def _copy_skill_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("probes.yaml", ".DS_Store", "__pycache__"),
    )


def run_isolated_container(
    root: Path,
    row: MatrixRow,
    attempt_dir: Path,
) -> ContainerRunOutput:
    """Execute one completely isolated Docker container run and capture every artifact."""
    spec = load_study_spec(root)
    image = os.environ.get("SKILLEVAL_DOCKER_IMAGE") or spec["runtime"]["docker_image"]
    volume = os.environ.get("SKILLEVAL_CLAUDE_AUTH_VOLUME") or spec["runtime"]["auth_volume"]
    img_id = docker_image_id(image)
    if not img_id:
        raise RuntimeError(
            f"Docker image '{image}' is not built yet. Run `uv run skilleval docker-build` first."
        )

    task_dir = root / "tasks" / row.task_id
    starter_dir = task_dir / "starter"
    prompt_file = task_dir / "prompt.md"
    if not starter_dir.is_dir() or not prompt_file.is_file():
        raise FileNotFoundError(
            f"Task '{row.task_id}' is missing starter/ or prompt.md at {task_dir}"
        )

    capture_dir = attempt_dir / "capture"
    capture_dir.mkdir(parents=True, exist_ok=True)
    deliverables_dir = attempt_dir / "deliverables"
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    base_prompt = prompt_file.read_text(encoding="utf-8")
    final_prompt = render_user_prompt(base_prompt, row.condition, row.target_skill)
    (capture_dir / "prompt.txt").write_text(final_prompt, encoding="utf-8")
    prompt_hash = sha256_text(final_prompt)

    with tempfile.TemporaryDirectory(prefix=f"skilleval-{row.run_id}-") as tmp:
        stage = Path(tmp)
        workspace = stage / "workspace"
        control = stage / "control"
        control.mkdir(parents=True)

        shutil.copytree(starter_dir, workspace)

        # Initialize clean git baseline inside workspace so `workspace.patch` captures exact diff
        git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "skilleval",
            "GIT_AUTHOR_EMAIL": "skilleval@local",
            "GIT_COMMITTER_NAME": "skilleval",
            "GIT_COMMITTER_EMAIL": "skilleval@local",
        }
        subprocess.run(["git", "init", "-q"], cwd=workspace, env=git_env, check=True)
        subprocess.run(["git", "add", "-A"], cwd=workspace, env=git_env, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "baseline"], cwd=workspace, env=git_env, check=True
        )

        # Mount skills strictly according to condition
        preload_hash: str | None = None
        if row.condition in ("B", "C1"):
            skills_target_root = workspace / ".claude" / "skills"
            skills_target_root.mkdir(parents=True, exist_ok=True)
            for sname in row.installed_skills:
                _copy_skill_tree(root / "skills" / sname, skills_target_root / sname)
        elif row.condition == "C2" and row.preload_skill:
            preload_src = root / "skills" / row.preload_skill / "SKILL.md"
            if not preload_src.is_file():
                raise FileNotFoundError(f"Missing preload SKILL.md: {preload_src}")
            preload_dst = control / "preload-skill.md"
            shutil.copyfile(preload_src, preload_dst)
            preload_hash = sha256_file(preload_dst)

        # Write control files: settings.json, empty mcp.json, capture hook script
        settings = _build_claude_settings(row)
        (control / "settings.json").write_text(
            json.dumps(settings, indent=2), encoding="utf-8"
        )
        (control / "mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
        shutil.copyfile(root / "docker" / "capture_hook.py", control / "capture_hook.py")
        (control / "prompt.txt").write_text(final_prompt, encoding="utf-8")

        tools_csv = ",".join(settings["permissions"]["allow"])
        claude_args = [
            "claude",
            "-p",
            "--model",
            row.model,
            "--effort",
            spec["studies"][row.study_id].get("effort", "medium"),
            "--max-turns",
            str(row.max_turns),
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--setting-sources",
            "project",
            "--settings",
            "/control/settings.json",
            "--strict-mcp-config",
            "--mcp-config",
            "/control/mcp.json",
            "--no-session-persistence",
            "--no-chrome",
            "--permission-mode",
            "dontAsk",
            "--tools",
            tools_csv,
        ]
        if row.condition == "C2" and preload_hash is not None:
            claude_args.extend(["--append-system-prompt-file", "/control/preload-skill.md"])

        (capture_dir / "command.json").write_text(
            json.dumps(claude_args, indent=2), encoding="utf-8"
        )

        # Container runs with ephemeral copy of OAuth volume into /tmp/claude-home
        # so runs NEVER share session history or state across containers!
        container_name = f"skilleval-{row.run_id.lower()}-{int(time.time())}"
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-w",
            "/workspace",
            "-v",
            f"{workspace}:/workspace:rw",
            "-v",
            f"{control}:/control:ro",
            "-v",
            f"{capture_dir}:/capture:rw",
            "-v",
            f"{volume}:/claude-auth-ro:ro",
            "-e",
            "GIT_CONFIG_GLOBAL=/dev/null",
            "-e",
            "GIT_CONFIG_NOSYSTEM=1",
            "-e",
            "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1",
            "-e",
            "DISABLE_DOCTOR_COMMAND=1",
            "-e",
            "DISABLE_PLUGIN_AUTOLOAD=1",
            image,
            "/usr/local/bin/skilleval-entrypoint.sh",
            *claude_args,
        ]

        session_file = capture_dir / "session.jsonl"
        stderr_file = capture_dir / "stderr.txt"
        started = time.monotonic()
        timed_out = False
        exit_code = 1

        with session_file.open("wb") as out_fh, stderr_file.open("wb") as err_fh:
            try:
                proc = subprocess.run(
                    docker_cmd,
                    stdout=out_fh,
                    stderr=err_fh,
                    timeout=row.timeout_seconds,
                    check=False,
                )
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = 124
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    check=False,
                )

        elapsed = round(time.monotonic() - started, 3)

        # Remove .claude before diffing/archiving so installed skills don't pollute workspace.patch
        claude_dir = workspace / ".claude"
        if claude_dir.exists():
            shutil.rmtree(claude_dir)

        # Capture full unified patch (tracked + untracked text files)
        subprocess.run(["git", "add", "-N", "."], cwd=workspace, env=git_env, check=False)
        diff_proc = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            cwd=workspace,
            env=git_env,
            capture_output=True,
            check=False,
        )
        (capture_dir / "workspace.patch").write_bytes(diff_proc.stdout)

        # Copy all new or modified files into deliverables/
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace,
            env=git_env,
            capture_output=True,
            text=True,
            check=False,
        )
        for line in status_proc.stdout.splitlines():
            if len(line) < 4:
                continue
            rel = line[3:].strip().strip('"')
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            src_file = workspace / rel
            if (
                src_file.is_file()
                and not src_file.is_symlink()
                and src_file.stat().st_size <= 64 * 1024 * 1024
                and ".git" not in Path(rel).parts
                and "node_modules" not in Path(rel).parts
            ):
                dst_file = deliverables_dir / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src_file, dst_file)

        # Snapshot workspace copy for isolated post-run grading
        snapshot_dir = attempt_dir / "workspace_final"
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        shutil.copytree(
            workspace,
            snapshot_dir,
            ignore=shutil.ignore_patterns(".git", "__pycache__"),
        )

        stderr_text = stderr_file.read_text(encoding="utf-8", errors="replace")
        return ContainerRunOutput(
            exit_code=exit_code,
            agent_seconds=elapsed,
            timed_out=timed_out,
            docker_image_id=img_id,
            prompt_sha256=prompt_hash,
            preload_sha256=preload_hash,
            stderr_text=stderr_text,
        )
