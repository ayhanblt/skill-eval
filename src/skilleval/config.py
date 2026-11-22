"""Configuration loading, skill orthogonality enforcement, and matrix generation."""

from __future__ import annotations

import hashlib
import os
import random
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from skilleval.schemas import Condition, MatrixRow, TokenUsage

# Discipline skills have cross-task spillover on arbitrary coding tasks and MUST NEVER
# be mounted as distractors for another task.
NON_DISTRACTOR_SKILLS: frozenset[str] = frozenset(
    {"systematic-debugging", "test-driven-development"}
)


def project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "specs" / "study.yaml").is_file() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    raise FileNotFoundError(
        "Could not locate skill-eval project root (missing specs/study.yaml)."
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def load_env(root: Path) -> None:
    env_file = root / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)


def typesafe_api_key(root: Path) -> str:
    load_env(root)
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "TYPESAFE_API_KEY is not set. Copy .env.example to .env and add your Jev API key."
        )
    return key


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_study_spec(root: Path) -> dict[str, Any]:
    return load_yaml(root / "specs" / "study.yaml")


def load_rubric_spec(root: Path) -> dict[str, Any]:
    return load_yaml(root / "specs" / "rubric-global.yaml")


def load_pricing_spec(root: Path) -> dict[str, Any]:
    return load_yaml(root / "specs" / "pricing.yaml")


def load_skill_registry(root: Path) -> dict[str, Any]:
    return load_yaml(root / "specs" / "skill-registry.yaml")


def estimate_api_equivalent_cost(
    root: Path, model: str, tokens: TokenUsage | None
) -> float | None:
    if tokens is None:
        return None
    pricing = load_pricing_spec(root).get("models", {}).get(model)
    if not pricing:
        return None
    cost = (
        (tokens.input_tokens / 1_000_000) * float(pricing["input_per_mtok"])
        + (tokens.cache_creation_input_tokens / 1_000_000)
        * float(pricing["cache_write_per_mtok"])
        + (tokens.cache_read_input_tokens / 1_000_000)
        * float(pricing["cache_read_per_mtok"])
        + (tokens.output_tokens / 1_000_000) * float(pricing["output_per_mtok"])
    )
    return round(cost, 6)


def resolve_orthogonal_distractors(
    task_id: str, target_skill: str, registry: dict[str, Any], count: int = 5
) -> list[str]:
    """Select `count` strictly domain-orthogonal distractor skills with zero spillover."""
    skills_cfg: dict[str, Any] = registry.get("skills", {})
    explicit: list[str] | None = registry.get("task_distractors", {}).get(task_id)

    if explicit is not None:
        chosen = list(explicit)
    else:
        target_domain = (skills_cfg.get(target_skill) or {}).get("domain", "")
        chosen = [
            name
            for name, meta in skills_cfg.items()
            if name != target_skill
            and name not in NON_DISTRACTOR_SKILLS
            and meta.get("allow_as_distractor", True)
            and meta.get("domain") != target_domain
        ][:count]

    # Hard scientific invariant checks
    if len(chosen) != count:
        raise ValueError(
            f"Task {task_id} requires exactly {count} orthogonal distractors, got {len(chosen)}: {chosen}"
        )
    if target_skill in chosen:
        raise ValueError(f"Task {task_id} target skill '{target_skill}' appeared in distractors.")
    forbidden = set(chosen) & NON_DISTRACTOR_SKILLS
    if forbidden:
        raise ValueError(
            f"Task {task_id} includes non-orthogonal discipline skill(s) as distractors: {sorted(forbidden)}"
        )
    if len(set(chosen)) != len(chosen):
        raise ValueError(f"Task {task_id} contains duplicate distractors: {chosen}")
    return chosen


def build_matrix(root: Path, study_id: str) -> list[MatrixRow]:
    spec = load_study_spec(root)
    studies = spec.get("studies", {})
    if study_id not in studies:
        raise ValueError(f"Unknown study '{study_id}'. Available: {sorted(studies)}")

    study = studies[study_id]
    runtime = spec["runtime"]
    registry = load_skill_registry(root)
    tasks_list = spec["tasks"]
    distractor_count = int(runtime.get("distractor_count_per_task", 5))

    rows: list[MatrixRow] = []
    phase = study["phase"]
    models: list[str] = list(study["models"])
    conditions: list[Condition] = list(study["conditions"])
    repetitions = int(study["repetitions"])

    for task in tasks_list:
        task_id = task["id"]
        target_skill = task["target_skill"]
        distractors = resolve_orthogonal_distractors(
            task_id, target_skill, registry, count=distractor_count
        )
        max_turns = int(task.get("max_turns", runtime["default_max_turns"]))
        timeout_seconds = int(task.get("timeout_seconds", runtime["default_timeout_seconds"]))

        for condition in conditions:
            installed = sorted([target_skill, *distractors]) if condition in ("B", "C1") else []
            preload = target_skill if condition == "C2" else None
            for model in models:
                for rep in range(1, repetitions + 1):
                    rows.append(
                        MatrixRow(
                            run_id="",  # assigned after deterministic shuffle
                            study_id=study_id,
                            phase=phase,
                            task_id=task_id,
                            archetype=task["archetype"],
                            target_skill=target_skill,
                            condition=condition,
                            model=model,
                            repeat=rep,
                            installed_skills=installed,
                            preload_skill=preload,
                            max_turns=max_turns,
                            timeout_seconds=timeout_seconds,
                        )
                    )

    # Optional C2 (always-on system preload) ablation block
    c2_cfg = study.get("c2_ablation") or {}
    if c2_cfg.get("enabled"):
        c2_tasks = set(c2_cfg.get("tasks", []))
        c2_reps = int(c2_cfg.get("repetitions", 3))
        for task in tasks_list:
            if task["id"] not in c2_tasks:
                continue
            max_turns = int(task.get("max_turns", runtime["default_max_turns"]))
            timeout_seconds = int(
                task.get("timeout_seconds", runtime["default_timeout_seconds"])
            )
            for model in models:
                for rep in range(1, c2_reps + 1):
                    rows.append(
                        MatrixRow(
                            run_id="",
                            study_id=study_id,
                            phase=phase,
                            task_id=task["id"],
                            archetype=task["archetype"],
                            target_skill=task["target_skill"],
                            condition="C2",
                            model=model,
                            repeat=rep,
                            installed_skills=[],
                            preload_skill=task["target_skill"],
                            max_turns=max_turns,
                            timeout_seconds=timeout_seconds,
                        )
                    )

    rng = random.Random(int(study["seed"]))
    rng.shuffle(rows)
    prefix = "CAL" if phase == "calibration" else "RUN"
    width = max(3, len(str(len(rows))))
    for idx, row in enumerate(rows, start=1):
        row.run_id = f"{prefix}-{idx:0{width}d}"
    return rows


def render_user_prompt(base_prompt: str, condition: Condition, target_skill: str) -> str:
    """Apply condition-specific prompt policy cleanly.

    - A, B, C2: exact base prompt (C2 compares always-on system context vs C1 on-demand).
    - C1: explicit single-line instruction to invoke `<target_skill>` via the Skill tool.
    """
    clean = base_prompt.strip()
    if condition == "C1":
        return (
            f"Before implementing, invoke the `{target_skill}` skill using the Skill tool "
            f"and follow its instructions and references for this task.\n\n{clean}\n"
        )
    return f"{clean}\n"
