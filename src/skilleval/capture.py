"""Full-fidelity session capture and human-readable transcript generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skilleval.schemas import RunManifest, TokenUsage


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
    return events


def extract_session_telemetry(
    session_jsonl: Path,
) -> tuple[list[str], TokenUsage | None, str | None, float | None]:
    """Return (actual_models, token_usage, terminal_subtype, provider_cost_usd)."""
    events = iter_jsonl(session_jsonl)
    models: set[str] = set()
    final_result: dict[str, Any] | None = None

    for ev in events:
        if ev.get("type") == "assistant":
            msg = ev.get("message")
            if isinstance(msg, dict):
                model = msg.get("model")
                if isinstance(model, str) and model.startswith("claude-"):
                    models.add(model)
        elif ev.get("type") == "result":
            final_result = ev

    tokens: TokenUsage | None = None
    terminal_subtype: str | None = None
    provider_cost: float | None = None
    if final_result:
        terminal_subtype = final_result.get("subtype")
        raw_cost = final_result.get("total_cost_usd")
        provider_cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else None
        usage = final_result.get("usage")
        if isinstance(usage, dict):
            tokens = TokenUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
            )
    return sorted(models), tokens, terminal_subtype, provider_cost


def _clip(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated {len(text) - limit} chars; full data in session.jsonl]"


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def render_transcript_markdown(
    manifest: RunManifest,
    prompt_text: str,
    session_jsonl: Path,
    hook_events_jsonl: Path | None = None,
) -> str:
    """Build a complete, readable turn-by-turn transcript from raw capture logs."""
    events = iter_jsonl(session_jsonl)
    hooks = iter_jsonl(hook_events_jsonl) if hook_events_jsonl else []

    lines: list[str] = [
        f"# Run Transcript — `{manifest.run_id}`",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Study | `{manifest.study_id}` |",
        f"| Task | `{manifest.row.task_id}` (`{manifest.row.archetype}`) |",
        f"| Condition | `{manifest.row.condition}` (target: `{manifest.row.target_skill}`) |",
        f"| Model (requested / actual) | `{manifest.row.model}` / `{', '.join(manifest.actual_models) or 'n/a'}` |",
        f"| Repeat | `{manifest.row.repeat}` |",
        f"| Status / Terminal | `{manifest.status}` / `{manifest.terminal_subtype or 'n/a'}` |",
        f"| Agent Seconds | `{manifest.agent_seconds:.2f}s` |"
        if manifest.agent_seconds is not None
        else "| Agent Seconds | `n/a` |",
    ]
    if manifest.tokens:
        t = manifest.tokens
        lines.append(
            f"| Tokens (in / cache_w / cache_r / out) | "
            f"`{t.input_tokens:,} / {t.cache_creation_input_tokens:,} / "
            f"{t.cache_read_input_tokens:,} / {t.output_tokens:,}` |"
        )
    if manifest.api_equivalent_cost_usd is not None:
        lines.append(f"| API-Equivalent Cost | `${manifest.api_equivalent_cost_usd:.4f}` |")

    lines.extend(
        [
            "",
            "## Initial Prompt",
            "",
            "```markdown",
            prompt_text.strip(),
            "```",
            "",
        ]
    )

    if hooks:
        lines.extend(["## Hook Events (Skill & Tool Audit)", ""])
        for idx, h in enumerate(hooks, start=1):
            lines.append(
                f"{idx}. `{h.get('hook_event_name', 'hook')}` · "
                f"tool=`{h.get('tool_name', '-')}` · "
                f"`{json.dumps(h.get('tool_input', {}), ensure_ascii=False)[:240]}`"
            )
        lines.append("")

    lines.extend(["## Conversation & Tool Timeline", ""])

    tool_names_by_id: dict[str, str] = {}
    turn = 0
    for ev in events:
        etype = ev.get("type")
        if etype == "system" and ev.get("subtype") == "init":
            skills_visible = ev.get("skills") or []
            tools_visible = ev.get("tools") or []
            lines.extend(
                [
                    "### System Init",
                    f"- Visible skills: `{', '.join(skills_visible) or 'none'}`",
                    f"- Visible tools: `{', '.join(tools_visible) or 'none'}`",
                    "",
                ]
            )
            continue

        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue

        if etype == "assistant":
            turn += 1
            lines.append(f"### Turn {turn} — Assistant")
            lines.append("")
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    thought = str(block.get("thinking") or "").strip()
                    if thought:
                        lines.extend(
                            [
                                "<details><summary>Thinking</summary>",
                                "",
                                "```text",
                                _clip(thought, 3000),
                                "```",
                                "</details>",
                                "",
                            ]
                        )
                elif btype == "text":
                    txt = str(block.get("text") or "").strip()
                    if txt:
                        lines.extend([txt, ""])
                elif btype == "tool_use":
                    tid = str(block.get("id") or "")
                    tname = str(block.get("name") or "unknown")
                    if tid:
                        tool_names_by_id[tid] = tname
                    tinput = json.dumps(block.get("input", {}), ensure_ascii=False, indent=2)
                    lines.extend(
                        [
                            f"**Tool Call:** `{tname}` (`{tid}`)",
                            "```json",
                            _clip(tinput, 2500),
                            "```",
                            "",
                        ]
                    )
        elif etype == "user":
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tid = str(block.get("tool_use_id") or "")
                tname = tool_names_by_id.get(tid, "tool")
                is_err = bool(block.get("is_error"))
                badge = "ERROR" if is_err else "OK"
                out_text = _stringify_content(block.get("content")).strip()
                lines.extend(
                    [
                        f"**Tool Result [{badge}]:** `{tname}` (`{tid}`)",
                        "```text",
                        _clip(out_text, 3500),
                        "```",
                        "",
                    ]
                )

    return "\n".join(lines).rstrip() + "\n"
