"""Session trace analyzer: 4-class error taxonomy, process discipline, and 3-layer skill probes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from skilleval.capture import iter_jsonl
from skilleval.schemas import (
    AdherenceState,
    ErrorClass,
    ExposureLevel,
    ProbeOutcome,
    RunManifest,
    ToolErrorEvent,
    TraceSummary,
)

EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
READ_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "Skill"})

INFRA_ERROR_PATTERNS = (
    re.compile(r"\.gitconfig.*operation not permitted", re.IGNORECASE),
    re.compile(r"sandbox.*unavailable|seatbelt|bwrap", re.IGNORECASE),
    re.compile(r"temporary failure in name resolution|econnreset|etimedout", re.IGNORECASE),
    re.compile(r"no space left on device|cannot allocate memory", re.IGNORECASE),
    re.compile(r"permission denied.*(/root|/home|/users)", re.IGNORECASE),
)

EXPECTED_NEGATIVE_CMD_PATTERNS = (
    re.compile(r"\b(pytest|unittest|vitest|jest|npm\s+test|pnpm\s+test|node\s+--test)\b", re.IGNORECASE),
    re.compile(r"\b(test\s+-[efdr]|which\s+|command\s+-v)\b", re.IGNORECASE),
)

VERIFY_CMD_PATTERNS = (
    re.compile(
        r"\b(pytest|unittest|vitest|jest|npm\s+(run\s+)?(test|build|lint|typecheck)|"
        r"tsc\b|ruff\b|mypy\b|node\s+render|ffmpeg|ffprobe|soffice|libreoffice|"
        r"psql\b|EXPLAIN|playwright|curl\s+.*localhost|"
        r"pg_local\.sh\s+test|build_release\.py|recalc\.py|pdftoppm|pdftotext|"
        r"remotion\s+render|python3?\s+build_model\.py)\b",
        re.IGNORECASE,
    ),
)

_HEREDOC_BODY_RE = re.compile(
    r"(<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?[^\n]*\n)(?:.*?\n)\2(?=\s*(?:\n|$))",
    re.DOTALL,
)
_BASH_REDIRECT_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:cat|echo|printf)\s+[^|;&\n]*?>>?\s*[\"']?([^\"'\s;|&]+)[\"']?"
)
_BASH_TEE_RE = re.compile(r"\btee\s+(?:-a\s+)?[\"']?([^\"'\s;|&]+)[\"']?")
_BASH_SED_INPLACE_RE = re.compile(r"\bsed\s+-i[^\n]*?\s+[\"']?([^\"'\s;|&]+)[\"']?")
_PY_OPEN_WRITE_RE = re.compile(r"open\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"'][wa]")
_PY_PATH_WRITE_RE = re.compile(
    r"Path\(\s*[\"']([^\"']+)[\"']\s*\)\.write_(?:text|bytes)\("
)

ASSERTION_FAILURE_PATTERNS = (
    re.compile(r"AssertionError|FAILED\s+\(|FAIL\s+|assert\s+.*==|Expected:|expect\(", re.IGNORECASE),
)
SYNTAX_IMPORT_FAILURE_PATTERNS = (
    re.compile(r"SyntaxError|ImportError|ModuleNotFoundError|Cannot find module|TS\d{4}", re.IGNORECASE),
)


def _extract_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def _classify_error(
    tool_name: str,
    tool_input: dict[str, Any],
    result_text: str,
    seen_signatures: dict[str, int],
    has_edited_production_code: bool,
) -> tuple[ErrorClass, str]:
    """Classify a tool error into the 4-class AERA-aligned error taxonomy."""
    for pat in INFRA_ERROR_PATTERNS:
        if pat.search(result_text):
            return "infra_sandbox", f"infra:{pat.pattern[:40]}"

    cmd = str(tool_input.get("command") or "")
    if tool_name == "Bash" and any(p.search(cmd) for p in EXPECTED_NEGATIVE_CMD_PATTERNS):
        # Running a test suite and getting an assertion failure (especially before/during fix)
        # is expected diagnostic/TDD red behavior, not a clumsy agent error — unless repeated identically.
        is_assertion = any(p.search(result_text) for p in ASSERTION_FAILURE_PATTERNS)
        is_syntax = any(p.search(result_text) for p in SYNTAX_IMPORT_FAILURE_PATTERNS)
        if is_assertion and not is_syntax:
            return "expected_negative", "expected_test_assertion_fail"
        if re.search(r"\b(test\s+-[efdr]|which\s+|command\s+-v)\b", cmd):
            return "expected_negative", "expected_probe_check"

    # Build a stable error signature to detect repeated identical mistakes
    norm_err = re.sub(r"\s+", " ", result_text.strip())[:120].lower()
    target = str(tool_input.get("file_path") or tool_input.get("path") or cmd[:60]).lower()
    signature = f"{tool_name}|{target}|{norm_err[:80]}"
    prior_count = seen_signatures.get(signature, 0)
    seen_signatures[signature] = prior_count + 1

    if prior_count >= 1:
        return "repeated_or_unverified_error", f"repeated({prior_count + 1}x): {norm_err[:100]}"

    _ = has_edited_production_code
    return "recoverable_agent_error", norm_err[:140]


def _is_doc_only_path(path_str: str) -> bool:
    return path_str.strip().lower().endswith(".md")


def _extract_bash_written_paths(cmd: str) -> tuple[list[str], int]:
    """Return `(written_workspace_paths, last_write_char_pos)` for file edits performed via Bash."""
    if not cmd.strip():
        return [], -1

    shell_headers = _HEREDOC_BODY_RE.sub(r"\1", cmd)
    raw_matches: list[tuple[str, int]] = []
    for pat in (_BASH_REDIRECT_RE, _BASH_TEE_RE, _BASH_SED_INPLACE_RE):
        for m in pat.finditer(shell_headers):
            raw_matches.append((m.group(1), m.end()))
    for pat in (_PY_OPEN_WRITE_RE, _PY_PATH_WRITE_RE):
        for m in pat.finditer(cmd):
            raw_matches.append((m.group(1), m.end()))

    paths: list[str] = []
    last_pos = -1
    for p, end_pos in raw_matches:
        cleaned = p.strip().strip("'\"")
        if not cleaned or cleaned.startswith(("/tmp/", "/dev/", "-")):
            continue
        paths.append(cleaned)
        last_pos = max(last_pos, end_pos)
    return paths, last_pos


def _is_test_path(path_str: str) -> bool:
    low = path_str.lower()
    return (
        "test" in low
        or "spec." in low
        or "__tests__" in low
        or low.endswith(("_test.py", ".test.ts", ".test.tsx", ".test.js", ".test.mjs"))
    )


def evaluate_probes(
    probes_path: Path,
    *,
    transcript_text: str,
    patch_text: str,
    deliverables_dir: Path,
    trace_meta: dict[str, Any],
) -> list[ProbeOutcome]:
    """Evaluate skill behavioral adherence probes across ALL conditions (A, B, C1, C2)."""
    if not probes_path.is_file():
        return []
    raw = yaml.safe_load(probes_path.read_text(encoding="utf-8")) or {}
    probes = raw.get("probes") or []
    outcomes: list[ProbeOutcome] = []

    deliverable_files = (
        [str(p.relative_to(deliverables_dir)) for p in deliverables_dir.rglob("*") if p.is_file()]
        if deliverables_dir.is_dir()
        else []
    )
    deliverable_concat = "\n".join(deliverable_files)

    for probe in probes:
        pid = str(probe["id"])
        desc = str(probe.get("description", pid))
        kind = str(probe.get("kind", "regex"))
        target = str(probe.get("target", "patch"))
        pattern = str(probe.get("pattern", ""))
        negate = bool(probe.get("negate", False))

        haystack = {
            "patch": patch_text,
            "transcript": transcript_text,
            "deliverables_list": deliverable_concat,
            "both": f"{patch_text}\n{transcript_text}",
        }.get(target, patch_text)

        state: AdherenceState = "not_applied"
        evidence = ""
        if kind == "regex" and pattern:
            match = re.search(pattern, haystack, re.MULTILINE | re.IGNORECASE)
            matched = match is not None
            if negate:
                state = "violated" if matched else "applied"
                evidence = f"Matched forbidden pattern: {match.group(0)[:80]}" if matched else "No violation"
            else:
                state = "applied" if matched else "not_applied"
                evidence = f"Matched: {match.group(0)[:80]}" if matched else "Pattern not observed"
        elif kind == "trace_flag":
            flag_name = str(probe.get("flag", ""))
            val = trace_meta.get(flag_name)
            if val is True:
                state, evidence = "applied", f"{flag_name}=True"
            elif val is False:
                state, evidence = "not_applied", f"{flag_name}=False"
            else:
                state, evidence = "not_applicable", f"{flag_name}=None"

        outcomes.append(
            ProbeOutcome(probe_id=pid, description=desc, state=state, evidence=evidence)
        )
    return outcomes


def analyze_trace(
    manifest: RunManifest,
    session_jsonl: Path,
    *,
    patch_path: Path | None = None,
    transcript_path: Path | None = None,
    deliverables_dir: Path | None = None,
    probes_path: Path | None = None,
) -> TraceSummary:
    """Analyze a single run's session.jsonl into structured process & skill metrics."""
    events = iter_jsonl(session_jsonl)
    target_skill = manifest.row.target_skill

    tool_uses: dict[str, dict[str, Any]] = {}
    tool_counts: dict[str, int] = {}
    turns = 0
    total_tool_calls = 0

    first_edit_turn: int | None = None
    read_steps_before_first_edit = 0
    edited_files: list[str] = []
    prod_edited = False
    red_test_before_prod_edit = False
    green_test_after_prod_edit = False
    last_edit_seq: float | None = None
    last_code_edit_seq: float | None = None
    last_verify_seq: float | None = None

    invoked_skill_ids: dict[str, str] = {}
    succeeded_skill_names: list[str] = []
    reference_files_read: set[str] = set()
    visible_skills: set[str] = set()

    error_events: list[ToolErrorEvent] = []
    seen_error_sigs: dict[str, int] = {}
    last_error_seq: int | None = None
    last_error_tool: str | None = None

    seq = 0
    for ev in events:
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            visible_skills.update(ev.get("skills") or [])
            continue

        msg = ev.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            continue

        if ev.get("type") == "assistant":
            turns += 1
            for block in msg["content"]:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                seq += 1
                total_tool_calls += 1
                tid = str(block.get("id") or f"call-{seq}")
                tname = str(block.get("name") or "unknown")
                tinput = block.get("input") if isinstance(block.get("input"), dict) else {}
                tool_counts[tname] = tool_counts.get(tname, 0) + 1
                tool_uses[tid] = {"name": tname, "input": tinput, "seq": seq, "turn": turns}

                if tname == "Skill":
                    sname = str(tinput.get("skill") or "")
                    if sname:
                        invoked_skill_ids[tid] = sname

                # Detect reading skill reference files
                if tname == "Read":
                    fpath = str(tinput.get("file_path") or "")
                    if f"/.claude/skills/{target_skill}/" in fpath and not fpath.endswith("SKILL.md"):
                        reference_files_read.add(fpath.split(f"/{target_skill}/", 1)[-1])

                # Track explore-before-edit & rework churn
                if tname in EDIT_TOOLS:
                    fpath = str(tinput.get("file_path") or tinput.get("path") or "")
                    if first_edit_turn is None:
                        first_edit_turn = turns
                    if fpath:
                        edited_files.append(fpath)
                        if not _is_test_path(fpath) and not _is_doc_only_path(fpath):
                            prod_edited = True
                            last_code_edit_seq = float(seq)
                    last_edit_seq = float(seq)
                elif tname in READ_TOOLS and first_edit_turn is None:
                    read_steps_before_first_edit += 1
                elif tname == "Bash":
                    cmd = str(tinput.get("command") or "")
                    bash_writes, _last_write_pos = _extract_bash_written_paths(cmd)
                    if bash_writes:
                        if first_edit_turn is None:
                            first_edit_turn = turns
                        for fpath in bash_writes:
                            edited_files.append(fpath)
                            if not _is_test_path(fpath) and not _is_doc_only_path(fpath):
                                prod_edited = True
                                last_code_edit_seq = float(seq)
                        last_edit_seq = float(seq)
                    elif first_edit_turn is None and re.search(
                        r"\b(ls|find|cat|head|tail|grep|rg|git\s+status|git\s+log|git\s+ls-files)\b", cmd
                    ):
                        read_steps_before_first_edit += 1

                    verify_hits = [m.start() for p in VERIFY_CMD_PATTERNS for m in p.finditer(cmd)]
                    if verify_hits:
                        if not bash_writes:
                            last_verify_seq = float(seq)
                        else:
                            # Compound write-then-test in one Bash call: mark tentative compound verify
                            if _last_write_pos < 0 or max(verify_hits) > _last_write_pos:
                                tool_uses[tid]["compound_verify"] = True

        elif ev.get("type") == "user":
            for block in msg["content"]:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                seq += 1
                tid = str(block.get("tool_use_id") or "")
                call = tool_uses.get(tid, {"name": "unknown", "input": {}, "seq": seq})
                tname = call["name"]
                tinput = call["input"]
                is_err = bool(block.get("is_error"))
                text = _extract_result_text(block.get("content"))

                if tid in invoked_skill_ids and not is_err:
                    succeeded_skill_names.append(invoked_skill_ids[tid])

                # TDD red-before-green & compound Bash self-verification detection
                if tname == "Bash":
                    if call.get("compound_verify") and not is_err:
                        last_verify_seq = float(call["seq"]) + 0.5
                    cmd = str(tinput.get("command") or "")
                    if any(p.search(cmd) for p in EXPECTED_NEGATIVE_CMD_PATTERNS):
                        if is_err and not prod_edited:
                            if any(p.search(text) for p in ASSERTION_FAILURE_PATTERNS) and not any(
                                p.search(text) for p in SYNTAX_IMPORT_FAILURE_PATTERNS
                            ):
                                red_test_before_prod_edit = True
                        elif not is_err and prod_edited:
                            green_test_after_prod_edit = True

                if is_err:
                    err_class, summary = _classify_error(
                        tname, tinput, text, seen_error_sigs, prod_edited
                    )
                    chained = (
                        last_error_seq is not None
                        and (seq - last_error_seq) <= 3
                        and last_error_tool == tname
                        and err_class == "recoverable_agent_error"
                    )
                    error_events.append(
                        ToolErrorEvent(
                            event_index=seq,
                            tool_name=tname,
                            tool_use_id=tid,
                            error_class=err_class,
                            chained_with_previous=chained,
                            summary=summary,
                        )
                    )
                    last_error_seq = seq
                    last_error_tool = tname

    # Collapse chained errors when counting penalty episodes
    error_counts: dict[ErrorClass, int] = {
        "infra_sandbox": 0,
        "expected_negative": 0,
        "recoverable_agent_error": 0,
        "repeated_or_unverified_error": 0,
    }
    for err in error_events:
        if not err.chained_with_previous:
            error_counts[err.error_class] += 1

    # Rework / churn ratio
    total_edits = len(edited_files)
    unique_edits = len(set(edited_files))
    rework_ratio = round((total_edits - unique_edits) / total_edits, 3) if total_edits > 0 else 0.0
    effective_edit_seq = last_code_edit_seq if last_code_edit_seq is not None else last_edit_seq
    self_verified = (
        effective_edit_seq is not None
        and last_verify_seq is not None
        and last_verify_seq > effective_edit_seq
    )
    tdd_ok = (
        (red_test_before_prod_edit and green_test_after_prod_edit)
        if prod_edited
        else None
    )

    # Determine 3-layer Skill Exposure
    invoked_unique = list(dict.fromkeys(succeeded_skill_names))
    wrong_distractors = [s for s in invoked_unique if s != target_skill]
    if manifest.row.condition == "C2" and manifest.preload_sha256:
        exposure: ExposureLevel = "preloaded"
    elif target_skill in invoked_unique and reference_files_read:
        exposure = "references_read"
    elif target_skill in invoked_unique:
        exposure = "invoked_target"
    elif wrong_distractors:
        exposure = "invoked_wrong_distractor"
    elif target_skill in visible_skills or manifest.row.installed_skills:
        exposure = "metadata_only"
    else:
        exposure = "none"

    patch_text = patch_path.read_text(encoding="utf-8", errors="replace") if patch_path and patch_path.is_file() else ""
    transcript_text = (
        transcript_path.read_text(encoding="utf-8", errors="replace")
        if transcript_path and transcript_path.is_file()
        else ""
    )
    probes = (
        evaluate_probes(
            probes_path,
            transcript_text=transcript_text,
            patch_text=patch_text,
            deliverables_dir=deliverables_dir or Path("/nonexistent"),
            trace_meta={
                "tdd_red_before_green": tdd_ok,
                "self_verified_after_last_edit": self_verified,
                "read_before_edit": read_steps_before_first_edit >= 2,
            },
        )
        if probes_path
        else []
    )

    return TraceSummary(
        run_id=manifest.run_id,
        total_turns=turns,
        total_tool_calls=total_tool_calls,
        tool_call_counts=tool_counts,
        raw_tool_errors=len(error_events),
        error_events=error_events,
        error_counts_by_class=error_counts,
        read_steps_before_first_edit=read_steps_before_first_edit,
        first_edit_turn=first_edit_turn,
        total_edit_calls=total_edits,
        unique_files_edited=unique_edits,
        rework_churn_ratio=rework_ratio,
        self_verified_after_last_edit=self_verified,
        tdd_red_before_green=tdd_ok,
        skill_exposure=exposure,
        invoked_skills=invoked_unique,
        wrong_distractor_skills_invoked=wrong_distractors,
        reference_files_read=sorted(reference_files_read),
        probe_outcomes=probes,
    )
