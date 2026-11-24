"""Structural, leakage, and completeness tests for all 8 task packages (G1-G8)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from skilleval.config import load_skill_registry, load_study_spec, project_root


def test_all_eight_tasks_complete_and_no_skill_leakage() -> None:
    root = project_root(Path(__file__).resolve().parent)
    spec = load_study_spec(root)
    registry = load_skill_registry(root)
    all_skill_names = sorted(registry["skills"].keys())

    assert len(spec["tasks"]) == 8
    for task in spec["tasks"]:
        tid = task["id"]
        tdir = root / "tasks" / tid
        assert (tdir / "task.yaml").is_file(), f"Missing task.yaml for {tid}"
        assert (tdir / "prompt.md").is_file(), f"Missing prompt.md for {tid}"
        assert (tdir / "starter").is_dir(), f"Missing starter/ for {tid}"
        assert (tdir / "grader" / "grade.py").is_file(), f"Missing grade.py for {tid}"
        assert (tdir / "reference" / "gold").is_dir(), f"Missing reference/gold for {tid}"

        neg_dir = tdir / "reference" / "negative-cases"
        negs = [p for p in neg_dir.iterdir() if p.is_dir()] if neg_dir.is_dir() else []
        assert len(negs) >= 2, f"{tid} needs >= 2 negative cases"
        for nd in negs:
            assert (nd / "expected.yaml").is_file(), f"{tid} negative {nd.name} missing expected.yaml"

        tyaml = yaml.safe_load((tdir / "task.yaml").read_text(encoding="utf-8"))
        jev_items = tyaml.get("jev_items") or []
        assert len(jev_items) == 5, f"{tid} expected 5 jev_items, got {len(jev_items)}"
        jev_ids = [it["id"] for it in jev_items]
        assert len(set(jev_ids)) == 5, f"{tid} has duplicate jev_item IDs"
        for it in jev_items:
            assert it.get("binary") is True, f"{tid}:{it['id']} must be binary"

        if task.get("visual_review"):
            assert len(tyaml.get("visual_items") or []) >= 2, f"{tid} missing visual_items"
        else:
            assert (tyaml.get("visual_items") or []) == [], f"{tid} non-visual must have empty visual_items"

        # Check all 4 Jev anchors cover every jev_item in both pass and fail polarities
        seen_pass: set[str] = set()
        seen_fail: set[str] = set()
        for anc_name in ("good_1", "good_2", "bad_1", "bad_2"):
            ep = tdir / "anchors" / anc_name / "expected.yaml"
            assert ep.is_file(), f"{tid} missing {ep}"
            exp = (yaml.safe_load(ep.read_text(encoding="utf-8")) or {}).get("expected") or {}
            assert set(exp.keys()) == set(jev_ids), f"{tid}/{anc_name} expected keys mismatch"
            for k, v in exp.items():
                assert v in ("pass", "fail")
                if v == "pass":
                    seen_pass.add(k)
                else:
                    seen_fail.add(k)
        assert seen_pass == set(jev_ids), f"{tid} anchors never test pass for {set(jev_ids) - seen_pass}"
        assert seen_fail == set(jev_ids), f"{tid} anchors never test fail for {set(jev_ids) - seen_fail}"

        # Ensure prompt.md NEVER leaks any skill ID or Skill tool invocation instruction
        prompt_text = (tdir / "prompt.md").read_text(encoding="utf-8")
        low = prompt_text.lower()
        assert "skill tool" not in low and "skill.md" not in low, f"Skill tool leak in {tid}/prompt.md"
        for sname in all_skill_names:
            assert not re.search(rf"(?<![.\w-]){re.escape(sname)}(?![\w-])", low), (
                f"Skill ID '{sname}' leaked into {tid}/prompt.md"
            )
