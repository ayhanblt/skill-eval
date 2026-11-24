"""Hidden deterministic grader for G2-remotion-display."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

DATASET_B = {
    "title": "2026 Renewable Grid Forecast",
    "subtitle": "Regional Storage Capacity & Dispatch Efficiency",
    "accentColor": "#F59E0B",
    "backgroundColor": "#0A2E22",
    "sceneDurationsSec": [2, 4, 4, 4],
    "kpis": [
        {"label": "Clean Share", "value": "78.4%", "delta": "+11.2% YoY"},
        {"label": "Grid Loss", "value": "2.1%", "delta": "-0.8% YoY"},
        {"label": "Storage Reserve", "value": "14.6 GWh", "delta": "+42% YoY"},
    ],
    "bars": [
        {"label": "Nordic Hydro", "value": 88, "unit": "%"},
        {"label": "Iberian Solar", "value": 74, "unit": "%"},
        {"label": "North Sea Wind", "value": 91, "unit": "%"},
    ],
    "takeaway": "Battery dispatch cut evening peak fossil backup across three interconnects.",
    "cta": "Inspect grid telemetry at energy.northstar.internal",
    "captions": [
        {
            "text": "Clean generation reached 78.4 percent across partner grid zones.",
            "startMs": 0,
            "endMs": 3000,
            "timestampMs": 1500,
            "confidence": 0.99,
        },
        {
            "text": "Transmission loss narrowed to 2.1 percent with new battery inverters.",
            "startMs": 3000,
            "endMs": 6000,
            "timestampMs": 4500,
            "confidence": 0.99,
        },
        {
            "text": "North Sea Wind and Nordic Hydro led regional capacity utilization.",
            "startMs": 6000,
            "endMs": 10000,
            "timestampMs": 8000,
            "confidence": 0.99,
        },
        {
            "text": "Storage buildout adds 6 gigawatt-hours before winter peak.",
            "startMs": 10000,
            "endMs": 14000,
            "timestampMs": 12000,
            "confidence": 0.99,
        },
    ],
}

DATASET_EDGE = {
    "title": "Minimal Edge Probe",
    "subtitle": "2 Bars & Empty Captions",
    "accentColor": "#EC4899",
    "backgroundColor": "#1E1B4B",
    "sceneDurationsSec": [2, 2, 2, 2],
    "kpis": [{"label": "Nodes", "value": "2", "delta": "stable"}],
    "bars": [
        {"label": "Alpha", "value": 10, "unit": "u"},
        {"label": "Beta", "value": 50, "unit": "u"},
    ],
    "takeaway": "Handles minimal bars and empty caption list cleanly.",
    "cta": "Done",
    "captions": [],
}

CONTAINER_SCRIPT = r"""
import json
import re
import subprocess
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

OUT_DIR = Path("/grade_out")
PREVIEWS = OUT_DIR / "_grader_previews"
PREVIEWS.mkdir(parents=True, exist_ok=True)
VIDEO_A = Path("/workspace/out/video.mp4")


def run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def extract_frame(video: Path, ts: float, out_png: Path) -> bool:
    p = run(["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(video), "-frames:v", "1", str(out_png)], timeout=30)
    return p.returncode == 0 and out_png.is_file()


def frame_std(png: Path) -> float:
    img = Image.open(png).convert("RGB")
    return sum(ImageStat.Stat(img).stddev) / 3.0


def frame_mad(png1: Path, png2: Path) -> float:
    i1 = Image.open(png1).convert("RGB")
    i2 = Image.open(png2).convert("RGB")
    diff = ImageChops.difference(i1, i2)
    return sum(ImageStat.Stat(diff).mean) / 3.0


def segment_mean_db(video: Path, extra_args: list[str]) -> float | None:
    p = run(["ffmpeg", "-v", "info", *extra_args, "-i", str(video), "-af", "volumedetect", "-f", "null", "-"], timeout=30)
    m = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", p.stderr)
    return float(m.group(1)) if m else None


def probe_video(video: Path) -> dict:
    p = run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json", str(video),
    ], timeout=30)
    if p.returncode != 0:
        return {"error": p.stderr}
    info = json.loads(p.stdout)
    streams = info.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    mean_db = segment_mean_db(video, []) if astreams else None
    head_db = segment_mean_db(video, ["-t", "0.45"]) if astreams else None
    mid_db = segment_mean_db(video, ["-ss", "3.0", "-t", "6.0"]) if astreams else None
    tail_db = segment_mean_db(video, ["-ss", "11.55", "-t", "0.45"]) if astreams else None
    v = vstreams[0] if vstreams else {}
    a = astreams[0] if astreams else {}
    dur = float((info.get("format") or {}).get("duration") or 0.0)
    return {
        "has_video": bool(vstreams),
        "has_audio": bool(astreams),
        "width": v.get("width"),
        "height": v.get("height"),
        "r_frame_rate": v.get("r_frame_rate"),
        "duration": dur,
        "audio_duration": float(a.get("duration") or dur or 0.0) if astreams else 0.0,
        "mean_volume_db": mean_db,
        "head_volume_db": head_db,
        "mid_volume_db": mid_db,
        "tail_volume_db": tail_db,
    }


def main():
    report = {}
    tsc = run(["npx", "tsc", "--noEmit"], timeout=60)
    report["tsc_ok"] = tsc.returncode == 0
    report["tsc_err"] = (tsc.stdout + "\n" + tsc.stderr)[-600:] if tsc.returncode != 0 else ""

    comps = run(["npx", "remotion", "compositions"], timeout=90)
    report["compositions_ok"] = comps.returncode == 0 and ("MetricStory" in comps.stdout)
    report["compositions_out"] = (comps.stdout + "\n" + comps.stderr)[-600:]

    probe_a = probe_video(VIDEO_A)
    report["probe_a"] = probe_a

    # Extract 5 frames from Dataset A video
    f_map = {
        "s1": (1.5, PREVIEWS / "scene1_intro.png"),
        "s2": (4.5, PREVIEWS / "scene2_kpis.png"),
        "s3_start": (6.2, Path("/tmp/s3_start.png")),
        "s3": (7.8, PREVIEWS / "scene3_bars.png"),
        "s4": (10.5, PREVIEWS / "scene4_outro.png"),
    }
    extracted = {k: extract_frame(VIDEO_A, ts, path) for k, (ts, path) in f_map.items()}
    report["frames_extracted"] = all(extracted.values())
    if report["frames_extracted"]:
        report["stds"] = {k: round(frame_std(p), 2) for k, (_, p) in f_map.items()}
        report["scene_diffs"] = {
            "s1_s2": round(frame_mad(f_map["s1"][1], f_map["s2"][1]), 2),
            "s2_s3": round(frame_mad(f_map["s2"][1], f_map["s3"][1]), 2),
            "s3_s4": round(frame_mad(f_map["s3"][1], f_map["s4"][1]), 2),
            "s3_motion": round(frame_mad(f_map["s3_start"][1], f_map["s3"][1]), 2),
            "caption_strip_diff": round(
                sum(
                    ImageStat.Stat(
                        ImageChops.difference(
                            Image.open(f_map["s1"][1]).convert("RGB").crop((100, 560, 1180, 710)),
                            Image.open(f_map["s3"][1]).convert("RGB").crop((100, 560, 1180, 710)),
                        )
                    ).mean
                ) / 3.0,
                2,
            ),
        }

    # Re-render with hidden Dataset B props ([2, 4, 4, 4] = 14s)
    video_b = Path("/tmp/video_b.mp4")
    ren_b = run([
        "npx", "remotion", "render", "MetricStory", str(video_b),
        "--props=/grade_scripts/dataset_b.json",
    ], timeout=180)
    report["render_b_ok"] = ren_b.returncode == 0 and video_b.is_file()
    report["render_b_err"] = (ren_b.stdout + "\n" + ren_b.stderr)[-600:] if ren_b.returncode != 0 else ""
    if report["render_b_ok"]:
        report["probe_b"] = probe_video(video_b)
        b_s1 = Path("/tmp/b_s1.png")
        b_s3 = PREVIEWS / "dataset_b_bars.png"
        if extract_frame(video_b, 1.0, b_s1) and extract_frame(video_b, 8.0, b_s3) and report["frames_extracted"]:
            report["ab_diffs"] = {
                "t1_0": round(frame_mad(f_map["s1"][1], b_s1), 2),
                "t8_0": round(frame_mad(f_map["s3"][1], b_s3), 2),
            }

    # Edge case: 2 bars + empty captions ([2, 2, 2, 2] = 8s)
    edge_dir = Path("/tmp/edge_frames")
    edge_dir.mkdir(parents=True, exist_ok=True)
    ren_edge = run([
        "npx", "remotion", "render", "MetricStory", str(edge_dir),
        "--props=/grade_scripts/dataset_edge.json",
        "--frames=120,160", "--image-format=png",
    ], timeout=120)
    report["edge_render_ok"] = ren_edge.returncode == 0 and len(list(edge_dir.glob("*.png"))) == 2
    report["edge_err"] = (ren_edge.stdout + "\n" + ren_edge.stderr)[-500:] if ren_edge.returncode != 0 else ""

    (OUT_DIR / "grade_payload.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def _resolve_root_comp_file(src_dir: Path) -> Path | None:
    root_tsx = src_dir / "Root.tsx"
    if not root_tsx.is_file():
        return None
    root_txt = root_tsx.read_text(encoding="utf-8", errors="replace")
    m_comp = re.search(r"<Composition\b[^>]*\bid=[\"']MetricStory[\"'][^>]*>", root_txt, re.DOTALL)
    if not m_comp:
        return None
    m_name = re.search(r"component=\{([A-Za-z0-9_]+)\}", m_comp.group(0))
    if not m_name:
        return None
    comp_name = m_name.group(1)
    m_imp = re.search(
        rf"import\s+\{{[^}}]*\b{re.escape(comp_name)}\b[^}}]*\}}\s+from\s+[\"'](\.[^\"']+)[\"']",
        root_txt,
    )
    if not m_imp:
        return root_tsx
    rel = m_imp.group(1)
    for ext in (".tsx", ".ts", "/index.tsx", "/index.ts"):
        cand = (src_dir / f"{rel}{ext}").resolve()
        if cand.is_file():
            return cand
    return root_tsx


def _scan_sources(workspace: Path) -> dict[str, Any]:
    src_dir = workspace / "src"
    files = sorted(
        p for p in src_dir.rglob("*")
        if p.is_file() and p.suffix in {".ts", ".tsx", ".css"}
    ) if src_dir.is_dir() else []
    combined = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)

    css_anim_hits = re.findall(
        r"(?:^|[\s{;])(transition\s*:|@keyframes\b|animation\s*:)",
        combined,
        re.IGNORECASE | re.MULTILINE,
    )
    urls = [
        u for u in re.findall(r"https?://[^\s'\"`)]+", combined)
        if not u.startswith("http://www.w3.org/2000/svg")
    ]
    uses_remotion_media_audio = bool(
        re.search(r"import\s*\{[^}]*\bAudio\b[^}]*\}\s*from\s*[\"']@remotion/media[\"']", combined)
    )
    has_audio_volume_prop = bool(re.search(r"<Audio\b[^>]*\bvolume\s*=", combined, re.DOTALL))
    css_transform_hits = re.findall(r"(?:^|[\s{,])transform\s*:", combined, re.MULTILINE)
    individual_transform_props = bool(re.search(r"\b(?:translate|scale|rotate)\s*:", combined))
    has_easing_curve = bool(re.search(r"\bEasing\.(bezier|spring)\s*\(", combined))
    uses_zcolor = (
        "@remotion/zod-types" in combined
        and bool(re.search(r"\bzColor\s*\(", combined))
    )

    root_comp_file = _resolve_root_comp_file(src_dir)
    root_comp_scoped = False
    if root_comp_file is not None and root_comp_file.is_file():
        root_comp_txt = root_comp_file.read_text(encoding="utf-8", errors="replace")
        root_comp_scoped = ("useCurrentFrame" not in root_comp_txt) and ("useCurrentFrame" in combined)

    return {
        "file_count": len(files),
        "css_anim_hits": css_anim_hits,
        "external_urls": urls,
        "has_frame_hooks": ("useCurrentFrame" in combined) and (
            "interpolate" in combined or "spring" in combined
        ),
        "has_clamped_motion": (
            ("extrapolateLeft" in combined and "extrapolateRight" in combined)
            or "spring(" in combined
        ),
        "has_calculate_metadata": ("calculateMetadata" in combined and "sceneDurationsSec" in combined),
        "has_sequence": bool(re.search(r"<(Sequence|Series)\b", combined)),
        "has_audio_static": ("<Audio" in combined and "staticFile" in combined),
        "uses_remotion_media_audio": uses_remotion_media_audio,
        "has_audio_volume_prop": has_audio_volume_prop,
        "css_transform_hits": css_transform_hits,
        "individual_transform_props": individual_transform_props,
        "has_easing_curve": has_easing_curve,
        "uses_zcolor": uses_zcolor,
        "root_comp_scoped": root_comp_scoped,
        "root_comp_file": root_comp_file.name if root_comp_file else None,
    }


def grade(
    run_id: str,
    workspace: Path,
    deliverables: Path,
    task_dir: Path,
) -> GradeResult:
    _ = task_dir
    video_a = workspace / "out" / "video.mp4"
    if not video_a.is_file():
        return GradeResult(
            run_id=run_id,
            task_id="G2-remotion-display",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
            checks=[
                CheckOutcome(
                    id="g2_video_exists",
                    dimension="correctness_completeness",
                    critical=True,
                    passed=False,
                    detail="Missing out/video.mp4",
                )
            ],
        )

    src_scan = _scan_sources(workspace)

    with tempfile.TemporaryDirectory(prefix="g2-grade-") as tmp:
        tdir = Path(tmp)
        script_path = tdir / "inspect_remotion.py"
        script_path.write_text(CONTAINER_SCRIPT, encoding="utf-8")
        b_path = tdir / "dataset_b.json"
        b_path.write_text(json.dumps(DATASET_B, indent=2), encoding="utf-8")
        edge_path = tdir / "dataset_edge.json"
        edge_path.write_text(json.dumps(DATASET_EDGE, indent=2), encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()

        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/inspect_remotion.py"],
            extra_mounts={
                script_path: "/grade_scripts/inspect_remotion.py",
                b_path: "/grade_scripts/dataset_b.json",
                edge_path: "/grade_scripts/dataset_edge.json",
            },
            output_dir=out_dir,
            timeout=240,
            network_none=True,
            link_node_modules=True,
        )
        payload_file = out_dir / "grade_payload.json"
        if proc.returncode != 0 or not payload_file.is_file():
            return GradeResult(
                run_id=run_id,
                task_id="G2-remotion-display",
                status="grader_error",
                gates=GateResults(
                    G1_CONTRACT_BUILD=False,
                    G2_CRITICAL_CORRECTNESS=False,
                    G3_CRITICAL_SAFETY_RULES=False,
                ),
                error_detail=f"Sandbox inspect failed ({proc.returncode}): {proc.stderr[-600:]}",
            )
        data = json.loads(payload_file.read_text(encoding="utf-8"))

        deliv_prev = deliverables / "_grader_previews"
        deliv_prev.mkdir(parents=True, exist_ok=True)
        visual_previews: list[str] = []
        src_prev = out_dir / "_grader_previews"
        if src_prev.is_dir():
            for png in sorted(src_prev.glob("*.png")):
                dst = deliv_prev / png.name
                dst.write_bytes(png.read_bytes())
                visual_previews.append(f"deliverables/_grader_previews/{png.name}")

    pa = data.get("probe_a", {})
    pb = data.get("probe_b", {})
    stds = data.get("stds", {})
    sdiff = data.get("scene_diffs", {})
    abdiff = data.get("ab_diffs", {})

    tsc_ok = bool(data.get("tsc_ok"))
    comp_ok = bool(data.get("compositions_ok"))
    specs_ok = (
        bool(pa.get("has_video"))
        and pa.get("width") == 1280
        and pa.get("height") == 720
        and pa.get("r_frame_rate") in ("30/1", "30")
        and 11.5 <= float(pa.get("duration") or 0.0) <= 12.5
    )
    audio_ok = (
        bool(pa.get("has_audio"))
        and float(pa.get("audio_duration") or 0.0) >= 10.0
        and (pa.get("mean_volume_db") is not None and float(pa["mean_volume_db"]) > -45.0)
    )
    head_db = pa.get("head_volume_db")
    mid_db = pa.get("mid_volume_db")
    tail_db = pa.get("tail_volume_db")
    acoustic_fade_ok = (
        head_db is not None
        and mid_db is not None
        and tail_db is not None
        and (float(mid_db) - float(head_db)) >= 2.5
        and (float(mid_db) - float(tail_db)) >= 2.5
    )
    media_audio_fade_ok = (
        src_scan["uses_remotion_media_audio"]
        and src_scan["has_audio_volume_prop"]
        and acoustic_fade_ok
    )

    non_blank_ok = bool(stds) and all(v > 10.0 for v in stds.values())
    scenes_distinct_ok = (
        float(sdiff.get("s1_s2", 0.0)) > 8.0
        and float(sdiff.get("s2_s3", 0.0)) > 8.0
        and float(sdiff.get("s3_s4", 0.0)) > 8.0
        and float(sdiff.get("s3_motion", 0.0)) > 1.0
        and float(sdiff.get("caption_strip_diff", 0.0)) > 2.0
    )
    dataset_b_ok = (
        bool(data.get("render_b_ok"))
        and bool(pb.get("has_audio"))
        and 13.5 <= float(pb.get("duration") or 0.0) <= 14.5
        and float(abdiff.get("t1_0", 0.0)) > 10.0
        and float(abdiff.get("t8_0", 0.0)) > 10.0
    )
    edge_ok = bool(data.get("edge_render_ok"))
    no_css_anim_ok = len(src_scan["css_anim_hits"]) == 0
    offline_only_ok = len(src_scan["external_urls"]) == 0
    remotion_primitives_ok = (
        src_scan["has_frame_hooks"]
        and src_scan["has_clamped_motion"]
        and src_scan["has_calculate_metadata"]
        and src_scan["has_sequence"]
        and src_scan["has_audio_static"]
    )
    studio_transforms_ok = (
        len(src_scan["css_transform_hits"]) == 0
        and src_scan["individual_transform_props"]
        and src_scan["has_easing_curve"]
        and src_scan["has_clamped_motion"]
    )
    zcolor_ok = src_scan["uses_zcolor"]
    scoped_frame_ok = src_scan["root_comp_scoped"]

    g1_gate = tsc_ok and comp_ok and bool(pa.get("has_video"))
    g2_gate = specs_ok and audio_ok and non_blank_ok and scenes_distinct_ok and dataset_b_ok
    g3_gate = no_css_anim_ok and offline_only_ok and remotion_primitives_ok

    checks = [
        CheckOutcome(
            id="g2_typecheck_and_composition",
            dimension="correctness_completeness",
            critical=True,
            passed=tsc_ok and comp_ok,
            detail=f"tsc={tsc_ok}, MetricStory={comp_ok} {data.get('tsc_err', '')}",
        ),
        CheckOutcome(
            id="g2_video_dimensions_fps_duration",
            dimension="correctness_completeness",
            critical=True,
            passed=specs_ok,
            detail=f"probe={pa}",
        ),
        CheckOutcome(
            id="g2_audio_stream_audible",
            dimension="correctness_completeness",
            critical=True,
            passed=audio_ok,
            detail=f"has_audio={pa.get('has_audio')}, mean_db={pa.get('mean_volume_db')}",
        ),
        CheckOutcome(
            id="g2_scene_progression_and_motion",
            dimension="correctness_completeness",
            critical=True,
            passed=non_blank_ok and scenes_distinct_ok,
            detail=f"stds={stds}, diffs={sdiff}",
        ),
        CheckOutcome(
            id="g2_dataset_b_parametric_rerender",
            dimension="robustness_edge_cases",
            critical=True,
            passed=dataset_b_ok,
            detail=f"render_b_ok={data.get('render_b_ok')}, b_dur={pb.get('duration')}, ab_diffs={abdiff} {data.get('render_b_err', '')}",
        ),
        CheckOutcome(
            id="g2_edge_2_bars_empty_captions",
            dimension="robustness_edge_cases",
            passed=edge_ok,
            detail=f"edge_render_ok={edge_ok} {data.get('edge_err', '')}",
        ),
        CheckOutcome(
            id="g2_remotion_media_audio_and_fade",
            dimension="robustness_edge_cases",
            passed=media_audio_fade_ok,
            detail=(
                f"media_audio={src_scan['uses_remotion_media_audio']}, "
                f"volume_prop={src_scan['has_audio_volume_prop']}, "
                f"head_db={head_db}, mid_db={mid_db}, tail_db={tail_db}"
            ),
        ),
        CheckOutcome(
            id="g2_studio_editable_transforms_and_easing",
            dimension="code_output_maintainability",
            passed=studio_transforms_ok,
            detail=(
                f"css_transform_hits={src_scan['css_transform_hits']}, "
                f"indiv_props={src_scan['individual_transform_props']}, "
                f"easing={src_scan['has_easing_curve']}"
            ),
        ),
        CheckOutcome(
            id="g2_zod_color_picker_schema",
            dimension="code_output_maintainability",
            passed=zcolor_ok,
            detail=f"uses_zcolor={zcolor_ok}",
        ),
        CheckOutcome(
            id="g2_no_css_transitions_or_external_urls",
            dimension="solution_performance_security",
            critical=True,
            passed=no_css_anim_ok and offline_only_ok,
            detail=f"css_anim_hits={src_scan['css_anim_hits']}, urls={src_scan['external_urls']}",
        ),
        CheckOutcome(
            id="g2_remotion_frame_sequence_audio_primitives",
            dimension="solution_performance_security",
            critical=True,
            passed=remotion_primitives_ok,
            detail=f"hooks={src_scan['has_frame_hooks']}, seq={src_scan['has_sequence']}, audio={src_scan['has_audio_static']}",
        ),
        CheckOutcome(
            id="g2_scoped_frame_subscription",
            dimension="solution_performance_security",
            passed=scoped_frame_ok,
            detail=f"root_comp={src_scan['root_comp_file']}, scoped={scoped_frame_ok}",
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G2-remotion-display",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
        solution_performance={
            "duration_s": pa.get("duration"),
            "duration_b_s": pb.get("duration"),
            "mean_volume_db": pa.get("mean_volume_db"),
            "head_tail_fade_db": (
                round(min(float(mid_db) - float(head_db), float(mid_db) - float(tail_db)), 2)
                if (head_db is not None and mid_db is not None and tail_db is not None)
                else None
            ),
            "ab_diff_t1_0": abdiff.get("t1_0"),
        },
        visual_previews=visual_previews,
    )
