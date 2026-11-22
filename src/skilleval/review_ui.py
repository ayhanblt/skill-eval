"""Generate a self-contained anonymized Blind Visual & Adjudication HTML UI."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from skilleval.schemas import GradeResult, JudgeResult


def generate_blind_review_ui(study_dir: Path, seed: int = 20261209) -> Path:
    """Build an offline HTML app showing ONLY randomized blind codes (zero A/B/C/model leaks)."""
    runs_dir = study_dir / "runs"
    review_dir = study_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    existing_human = review_dir / "human-decisions.json"
    saved = (
        json.loads(existing_human.read_text(encoding="utf-8"))
        if existing_human.is_file()
        else {}
    )

    cards: list[dict[str, Any]] = []
    for run_dir in sorted(runs_dir.iterdir()):
        jpath = run_dir / "judge.json"
        if not jpath.is_file():
            continue
        judge = JudgeResult.model_validate_json(jpath.read_text(encoding="utf-8"))
        pending_text = [it for it in judge.items if it.needs_human_review]
        pending_visual = [it for it in judge.visual_items if it.needs_human_review]
        if not pending_text and not pending_visual:
            continue

        gpath = run_dir / "grade.json"
        previews: list[str] = []
        task_id = ""
        if gpath.is_file():
            grade = GradeResult.model_validate_json(gpath.read_text(encoding="utf-8"))
            task_id = grade.task_id
            for rel in grade.visual_previews:
                abs_img = (run_dir / rel).resolve()
                if abs_img.is_file():
                    previews.append(str(abs_img))

        patch_path = run_dir / "capture" / "workspace.patch"
        patch_snippet = (
            patch_path.read_text(encoding="utf-8", errors="replace")[:12000]
            if patch_path.is_file()
            else ""
        )

        cards.append(
            {
                "blind_code": judge.blind_code,
                "task_id": task_id,
                "previews": previews,
                "patch_snippet": patch_snippet,
                "items": [
                    {
                        "key": f"{judge.blind_code}:{it.item_id}",
                        "item_id": it.item_id,
                        "dimension": it.dimension,
                        "question": it.question,
                        "kind": "visual" if it.dimension == "visual_design" else "code_adjudication",
                    }
                    for it in (*pending_visual, *pending_text)
                ],
            }
        )

    random.Random(seed).shuffle(cards)

    payload_json = json.dumps({"cards": cards, "saved": saved}, ensure_ascii=False)
    out_path = review_dir / "blind-review.html"
    out_path.write_text(
        f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Skill-Eval · Anonim Kör Görsel & Hakemlik Arayüzü</title>
<style>
:root {{ font: 15px/1.55 system-ui, -apple-system, sans-serif; color: #16212c; background: #f3f6f8; }}
body {{ margin: 0; padding: 24px; max-width: 1120px; margin-inline: auto; }}
header {{ background: #102530; color: #f2fbfb; padding: 20px 24px; border-radius: 12px; margin-bottom: 18px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
button.primary {{ background: #0f9d8a; color: #fff; border: 0; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; }}
.card {{ background: #fff; border: 1px solid #d9e2e8; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
.meta {{ display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }}
.badge {{ background: #e8f4f6; color: #0c4d57; padding: 3px 10px; border-radius: 999px; font-weight: 600; font-size: 0.85rem; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; margin: 12px 0; }}
.gallery img {{ width: 100%; border: 1px solid #d0dbe2; border-radius: 8px; }}
pre {{ background: #0f1720; color: #e6eef5; padding: 14px; border-radius: 8px; overflow-x: auto; max-height: 360px; font-size: 0.82rem; }}
.qrow {{ border-top: 1px solid #e6edf2; padding: 12px 0; display: grid; gap: 8px; }}
.choices {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.choices button {{ border: 1px solid #bccad4; background: #fff; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-weight: 600; }}
.choices button.active[data-val="pass"] {{ background: #12805c; color: #fff; border-color: #12805c; }}
.choices button.active[data-val="partial"] {{ background: #c27803; color: #fff; border-color: #c27803; }}
.choices button.active[data-val="fail"] {{ background: #b42318; color: #fff; border-color: #b42318; }}
input.note {{ padding: 6px 10px; border: 1px solid #cad6df; border-radius: 6px; width: 100%; box-sizing: border-box; }}
</style>
</head>
<body>
<header>
  <div>
    <h1 style="margin:0;font-size:1.4rem;">Skill-Eval · Kör Değerlendirme Arayüzü</h1>
    <div id="progress" style="opacity:.85;font-size:.9rem;">Koşul (A/B/C1/C2), model ve Jev tahmini tamamen gizlidir.</div>
  </div>
  <button class="primary" onclick="exportDecisions()">human-decisions.json İndir</button>
</header>
<div id="root"></div>
<script>
const DATA = {payload_json};
const decisions = Object.assign({{}}, DATA.saved);

function updateProgress() {{
  let total = 0, done = 0;
  for (const c of DATA.cards) {{
    for (const it of c.items) {{
      total++;
      if (decisions[it.key] && decisions[it.key].decision) done++;
    }}
  }}
  document.getElementById('progress').textContent =
    `Tamamlanan: ${{done}} / ${{total}} madde · Koşul ve model bilgisi tamamen gizlidir.`;
}}

function setDecision(key, val, btn) {{
  decisions[key] = Object.assign({{}}, decisions[key], {{ decision: val }});
  for (const b of btn.parentElement.querySelectorAll('button')) b.classList.remove('active');
  btn.classList.add('active');
  updateProgress();
}}

function setNote(key, val) {{
  decisions[key] = Object.assign({{}}, decisions[key], {{ note: val }});
}}

function exportDecisions() {{
  const blob = new Blob([JSON.stringify(decisions, null, 2)], {{ type: 'application/json' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'human-decisions.json';
  a.click();
}}

function render() {{
  const root = document.getElementById('root');
  if (!DATA.cards.length) {{
    root.innerHTML = '<div class="card">İncelenecek bekleyen kör madde yok. Tüm kararlar tamamlanmış!</div>';
    updateProgress();
    return;
  }}
  for (const card of DATA.cards) {{
    const el = document.createElement('section');
    el.className = 'card';
    const imgs = card.previews.map(p => `<img src="file://${{p}}" alt="preview">`).join('');
    const patchHtml = card.patch_snippet
      ? `<details><summary style="cursor:pointer;font-weight:600;color:#0c4d57;">Diff / Kod Önizlemesi</summary><pre>${{card.patch_snippet.replace(/[&<>]/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[m]))}}</pre></details>`
      : '';
    el.innerHTML = `
      <div class="meta">
        <span class="badge">Kör Kod #${{card.blind_code}}</span>
        <span class="badge">${{card.task_id}}</span>
      </div>
      ${{imgs ? `<div class="gallery">${{imgs}}</div>` : ''}}
      ${{patchHtml}}
      <div class="questions"></div>
    `;
    const qbox = el.querySelector('.questions');
    for (const it of card.items) {{
      const cur = (decisions[it.key] || {{}}).decision || '';
      const note = (decisions[it.key] || {{}}).note || '';
      const row = document.createElement('div');
      row.className = 'qrow';
      row.innerHTML = `
        <div><strong>[${{it.kind === 'visual' ? 'Görsel' : 'Jev Hakemlik'}}]</strong> ${{it.question}}</div>
        <div class="choices">
          ${{['pass', 'partial', 'fail'].map(v => `<button data-val="${{v}}" class="${{cur===v?'active':''}}">${{v==='pass'?'Geçti (1.0)':v==='partial'?'Kısmi (0.5)':'Kaldı (0.0)'}}</button>`).join('')}}
        </div>
        <input class="note" placeholder="Opsiyonel kısa gerekçe notu..." value="${{note.replace(/"/g, '&quot;')}}">
      `;
      row.querySelectorAll('.choices button').forEach(btn => {{
        btn.onclick = () => setDecision(it.key, btn.dataset.val, btn);
      }});
      row.querySelector('input.note').oninput = e => setNote(it.key, e.target.value);
      qbox.appendChild(row);
    }}
    root.appendChild(el);
  }}
  updateProgress();
}}
render();
</script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return out_path
