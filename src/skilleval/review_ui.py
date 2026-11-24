"""Generate a self-contained anonymized Blind Visual & Adjudication HTML UI."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from skilleval.schemas import GradeResult, JudgeResult

VISUAL_QUESTION_TR: dict[str, dict[str, str]] = {
    "g1_visual_no_truncation": {
        "question": (
            "Tüm çalışma kitabı sayfalarında hücre taşması (###), üst üste binen metin "
            "veya kesilmiş başlık olmadan temiz bir görünüm var mı?"
        ),
        "scope": "Kapsam: Karttaki tüm Excel→PDF sayfalarını (Sayfa 1..N) birlikte değerlendirin.",
    },
    "g1_visual_exec_hierarchy": {
        "question": (
            "Özet KPI bloğu, gömülü grafik ve 12 aylık Nakit Akışı tablosu net görsel "
            "hiyerarşiye, okunaklı tipografiye ve dengeli sütun genişliklerine sahip mi?"
        ),
        "scope": "Kapsam: Karttaki tüm ilgili çalışma kitabı sayfalarını birlikte değerlendirin.",
    },
    "g2_visual_hierarchy_readability": {
        "question": (
            "Başlık, KPI kartları, çubuk grafik ve senkronize alt yazı bandı 1280×720 "
            "çözünürlükte keskin, dengeli ve okunaklı mı (metin kesilmesi veya çakışma olmadan)?"
        ),
        "scope": "Kapsam: Karttaki tüm sahne karelerini (Sahne 1–4 ve Dataset B) birlikte değerlendirin.",
    },
    "g2_visual_theme_adaptation": {
        "question": (
            "Dataset A sahneleri ile Dataset B karesi farklı arka plan rengine, vurgu rengine, "
            "dinamik çubuk sayısına ve alt yazılara temiz biçimde uyum sağlamış mı?"
        ),
        "scope": "Kapsam: Dataset A kareleri (Sahne 1–4) ile Dataset B karesini karşılaştırarak değerlendirin.",
    },
    "g6_visual_aesthetic_distinction": {
        "question": (
            "Botanik sera almanağı tutarlı ve özgün bir görsel zanaat sunuyor mu "
            "(renk paleti uyumu, tipografi hiyerarşisi, bilinçli boşluk kullanımı, "
            "jenerik şablon klişelerinden kaçınma)?"
        ),
        "scope": "Kapsam: Karttaki tüm masaüstü, tablet, mobil ve detay ekran görüntülerini birlikte değerlendirin.",
    },
    "g6_visual_desktop_mobile_balance": {
        "question": (
            "Masaüstü (1440px), tablet (768px) ve mobil (375px) görünümlerinde örnek kartları, "
            "karşılaştırma çekmecesi, telemetri ve detay penceresi temiz, dengeli ve okunaklı mı?"
        ),
        "scope": "Kapsam: Masaüstü, tablet, mobil ve modal ekran görüntülerinin tamamını birlikte değerlendirin.",
    },
}

_PREVIEW_CAPTIONS_TR = {
    "scene1_intro.png": "Sahne 1: Giriş (Dataset A)",
    "scene2_kpis.png": "Sahne 2: KPI Kartları (Dataset A)",
    "scene3_bars.png": "Sahne 3: Çubuk Grafik (Dataset A)",
    "scene4_outro.png": "Sahne 4: Kapanış (Dataset A)",
    "dataset_b_bars.png": "Dataset B: Tema & Dinamik Çubuk Kontrolü",
    "g6_desktop_1440.png": "Masaüstü (1440px)",
    "g6_desktop_full.png": "Masaüstü Tam Sayfa",
    "g6_desktop_modal.png": "Detay Penceresi / Çekmece",
    "g6_tablet_768.png": "Tablet (768px)",
    "g6_mobile_375.png": "Mobil (375px)",
}

_TASK_LABELS_TR = {
    "G1-xlsx-financial-model": "G1 · Finansal Model (Excel/PDF)",
    "G2-remotion-display": "G2 · Remotion Video Kareleri",
    "G6-frontend-design": "G6 · Web Arayüz Tasarımı",
}


def _preview_caption_tr(img_path: str) -> str:
    name = Path(img_path).name
    if name in _PREVIEW_CAPTIONS_TR:
        return _PREVIEW_CAPTIONS_TR[name]
    m = re.match(r"page-(\d+)\.png$", name)
    if m:
        return f"Sayfa {m.group(1)}"
    return name


def _task_label_tr(task_id: str) -> str:
    return _TASK_LABELS_TR.get(task_id, task_id)


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
        previews: list[dict[str, str]] = []
        task_id = ""
        if gpath.is_file():
            grade = GradeResult.model_validate_json(gpath.read_text(encoding="utf-8"))
            task_id = grade.task_id
            for rel in grade.visual_previews:
                abs_img = (run_dir / rel).resolve()
                if abs_img.is_file():
                    previews.append(
                        {
                            "path": str(abs_img),
                            "caption": _preview_caption_tr(str(abs_img)),
                        }
                    )

        patch_path = run_dir / "capture" / "workspace.patch"
        patch_snippet = (
            patch_path.read_text(encoding="utf-8", errors="replace")[:12000]
            if (pending_text and patch_path.is_file())
            else ""
        )

        card_items: list[dict[str, str]] = []
        for it in (*pending_visual, *pending_text):
            loc = VISUAL_QUESTION_TR.get(it.item_id, {})
            card_items.append(
                {
                    "key": f"{judge.blind_code}:{it.item_id}",
                    "item_id": it.item_id,
                    "dimension": it.dimension,
                    "question": loc.get("question", it.question),
                    "scope": loc.get("scope", ""),
                    "kind": "visual" if it.dimension == "visual_design" else "code_adjudication",
                }
            )

        cards.append(
            {
                "blind_code": judge.blind_code,
                "task_id": task_id,
                "task_label": _task_label_tr(task_id),
                "previews": previews,
                "patch_snippet": patch_snippet,
                "items": card_items,
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
header {{ background: #102530; color: #f2fbfb; padding: 20px 24px; border-radius: 12px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
.banner-note {{ background: #e8f4f6; color: #0c4d57; border: 1px solid #c5e1e6; padding: 10px 16px; border-radius: 10px; margin-bottom: 18px; font-size: .92rem; }}
button.primary {{ background: #0f9d8a; color: #fff; border: 0; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; }}
.card {{ background: #fff; border: 1px solid #d9e2e8; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
.meta {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }}
.badge {{ background: #e8f4f6; color: #0c4d57; padding: 3px 10px; border-radius: 999px; font-weight: 600; font-size: 0.85rem; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; margin: 12px 0; }}
.gallery figure {{ margin: 0; background: #f8fafb; border: 1px solid #d0dbe2; border-radius: 8px; overflow: hidden; }}
.gallery img {{ width: 100%; display: block; }}
.gallery figcaption {{ padding: 6px 10px; font-size: 0.82rem; font-weight: 600; color: #314351; border-top: 1px solid #e1e9ee; }}
pre {{ background: #0f1720; color: #e6eef5; padding: 14px; border-radius: 8px; overflow-x: auto; max-height: 360px; font-size: 0.82rem; }}
.qrow {{ border-top: 1px solid #e6edf2; padding: 12px 0; display: grid; gap: 8px; }}
.scope {{ font-size: 0.85rem; color: #475b69; }}
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
<div class="banner-note">
  Her kart tek bir anonim koşuyu gösterir; sorular tek tek resimler için değil, <strong>karttaki ilgili tüm görsellere birlikte bakılarak</strong> puanlanır. Görsellere tıklayarak tam boyutta açabilirsiniz.
</div>
<div id="root"></div>
<script>
const DATA = {payload_json};
const decisions = Object.assign({{}}, DATA.saved);

function escHtml(s) {{
  return String(s).replace(/[&<>"]/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[m]));
}}

function updateProgress() {{
  let total = 0, done = 0;
  for (const c of DATA.cards) {{
    for (const it of c.items) {{
      total++;
      if (decisions[it.key] && decisions[it.key].decision) done++;
    }}
  }}
  document.getElementById('progress').textContent =
    `Tamamlanan: ${{done}} / ${{total}} madde (${{DATA.cards.length}} kart) · Koşul ve model bilgisi tamamen gizlidir.`;
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
    const imgs = card.previews.map(p => {{
      const pPath = typeof p === 'string' ? p : p.path;
      const cap = typeof p === 'string' ? '' : (p.caption || '');
      return `<figure><a href="file://${{pPath}}" target="_blank" rel="noopener"><img src="file://${{pPath}}" alt="${{escHtml(cap)}}"></a>${{cap ? `<figcaption>${{escHtml(cap)}}</figcaption>` : ''}}</figure>`;
    }}).join('');
    const patchHtml = card.patch_snippet
      ? `<details><summary style="cursor:pointer;font-weight:600;color:#0c4d57;">Diff / Kod Önizlemesi</summary><pre>${{escHtml(card.patch_snippet)}}</pre></details>`
      : '';
    const label = card.task_label || card.task_id;
    el.innerHTML = `
      <div class="meta">
        <span class="badge">Kör Kod #${{card.blind_code}}</span>
        <span class="badge">${{escHtml(label)}}</span>
        <span class="badge">${{card.previews.length}} görsel</span>
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
        <div><strong>[${{it.kind === 'visual' ? 'Görsel' : 'Jev Hakemlik'}}]</strong> ${{escHtml(it.question)}}</div>
        ${{it.scope ? `<div class="scope">${{escHtml(it.scope)}}</div>` : ''}}
        <div class="choices">
          ${{['pass', 'partial', 'fail'].map(v => `<button data-val="${{v}}" class="${{cur===v?'active':''}}">${{v==='pass'?'Geçti (1.0)':v==='partial'?'Kısmi (0.5)':'Kaldı (0.0)'}}</button>`).join('')}}
        </div>
        <input class="note" placeholder="Opsiyonel kısa gerekçe notu..." value="${{escHtml(note)}}">
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
