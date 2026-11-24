"""Hidden deterministic grader for G6-frontend-design using Playwright + axe-core."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from skilleval.grader_utils import run_in_sandbox
from skilleval.schemas import CheckOutcome, GateResults, GradeResult

AUDIT_MJS = r"""
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const axe = require("axe-core");

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:4173";
const XSS_URL = process.env.XSS_URL || "http://127.0.0.1:4174";
const OUT_DIR = process.env.OUT_DIR || "/grade_out";
const PREVIEWS = path.join(OUT_DIR, "_grader_previews");
fs.mkdirSync(PREVIEWS, { recursive: true });

async function collectDesignMetrics(page) {
  return page.evaluate(() => {
    function rgbToHex(val) {
      if (!val) return "";
      const m = val.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
      if (!m) return val.trim().toLowerCase();
      return (
        "#" +
        [m[1], m[2], m[3]]
          .map((x) => Number(x).toString(16).padStart(2, "0"))
          .join("")
      );
    }
    function isVisible(el) {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden" || parseFloat(s.opacity) === 0) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    }

    const bodyStyle = getComputedStyle(document.body);
    const h1 = document.querySelector("h1");
    const h1Style = h1 ? getComputedStyle(h1) : null;
    const h1Px = h1Style ? parseFloat(h1Style.fontSize) || 0 : 0;
    const bodyPx = parseFloat(bodyStyle.fontSize) || 16;

    let uppercaseLabelCount = 0;
    let emDashLabelCount = 0;
    const labelNodes = document.querySelectorAll("h2, h3, h4, p, span, div, dt, label, a, button");
    for (const el of labelNodes) {
      if (el.closest("h1") || el.querySelector("p, div, section, article") || !isVisible(el)) continue;
      const raw = (el.textContent || "").trim();
      if (!raw || raw.length > 48) continue;
      const st = getComputedStyle(el);
      const hasLetters = /[A-Za-z]{2,}/.test(raw);
      if (hasLetters && (st.textTransform === "uppercase" || (raw === raw.toUpperCase() && raw !== raw.toLowerCase()))) {
        uppercaseLabelCount += 1;
      }
      if (/^[A-Z0-9]{2,}\s+—\s+/.test(raw)) {
        emDashLabelCount += 1;
      }
    }

    const bodyText = (document.body.innerText || "");
    const middleDotCount = (bodyText.match(/\u00b7/g) || []).length;

    let arrowCtaCount = 0;
    for (const el of document.querySelectorAll("button, a")) {
      if (isVisible(el) && (el.innerText || "").includes("\u2192")) {
        arrowCtaCount += 1;
      }
    }

    let maxParagraphWidthPx = 0;
    for (const p of document.querySelectorAll("p")) {
      if (!isVisible(p)) continue;
      const txt = (p.innerText || "").trim();
      if (txt.length < 30) continue;
      const w = Math.round(p.getBoundingClientRect().width);
      if (w > maxParagraphWidthPx) maxParagraphWidthPx = w;
    }

    const submitBtn = document.querySelector("form button[type='submit'], form input[type='submit']");
    const submitButtonText = submitBtn ? ((submitBtn.innerText || submitBtn.value || "").trim()) : "";

    return {
      body_bg_hex: rgbToHex(bodyStyle.backgroundColor),
      body_color_hex: rgbToHex(bodyStyle.color),
      body_font_family: bodyStyle.fontFamily,
      h1_font_family: h1Style ? h1Style.fontFamily : "",
      h1_font_size_px: Math.round(h1Px * 100) / 100,
      body_font_size_px: Math.round(bodyPx * 100) / 100,
      h1_to_body_ratio: bodyPx > 0 ? Math.round((h1Px / bodyPx) * 100) / 100 : 0,
      uppercase_label_count: uppercaseLabelCount,
      middle_dot_count: middleDotCount,
      arrow_cta_count: arrowCtaCount,
      em_dash_label_count: emDashLabelCount,
      max_paragraph_width_px: maxParagraphWidthPx,
      submit_button_text: submitButtonText,
    };
  });
}

async function runAudit() {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const report = {
    externalRequests: [],
    pageErrors: [],
    consoleErrors: [],
  };

  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    page.on("request", (req) => {
      const u = req.url();
      if (!u.startsWith("http://127.0.0.1:") && !u.startsWith("http://localhost:") && !u.startsWith("data:") && !u.startsWith("blob:")) {
        report.externalRequests.push(u);
      }
    });
    page.on("pageerror", (err) => report.pageErrors.push(String(err)));
    page.on("console", (msg) => {
      if (msg.type() === "error") report.consoleErrors.push(msg.text());
    });

    const resp = await page.goto(BASE_URL + "/index.html", { waitUntil: "networkidle" });
    report.httpStatus = resp ? resp.status() : 0;
    await page.waitForTimeout(300);

    // 1. Landmarks, h1, specimen count, desktop overflow, factual design telemetry
    const domCheck = await page.evaluate(() => {
      const cards = document.querySelectorAll("[data-specimen-card]");
      const h1s = document.querySelectorAll("h1");
      const hasHeader = !!document.querySelector("header, [role='banner']");
      const hasMain = !!document.querySelector("main, [role='main']");
      const hasNav = !!document.querySelector("nav, [role='navigation']");
      return {
        cardCount: cards.length,
        h1Count: h1s.length,
        hasHeader,
        hasMain,
        hasNav,
        overflowDesktop: document.documentElement.scrollWidth > window.innerWidth + 2,
        scrollWidthDesktop: document.documentElement.scrollWidth,
        innerWidthDesktop: window.innerWidth,
      };
    });
    Object.assign(report, domCheck);
    report.designMetrics = await collectDesignMetrics(page);

    await page.screenshot({ path: path.join(PREVIEWS, "g6_desktop_1440.png"), fullPage: false });
    await page.screenshot({ path: path.join(PREVIEWS, "g6_desktop_full.png"), fullPage: true });

    // 2. Desktop axe-core audit
    await page.addScriptTag({ content: axe.source });
    const axeDesktop = await page.evaluate(() =>
      window.axe.run({ runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] } })
    );
    report.axeDesktopSevere = axeDesktop.violations
      .filter((v) => v.impact === "critical" || v.impact === "serious")
      .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));

    // 3. Biome filter interaction (Cloud Forest -> 4 cards, All -> 12 cards)
    const cloudBtn = page.getByRole("button", { name: /Cloud Forest/i }).first();
    if (await cloudBtn.count()) {
      await cloudBtn.click();
      await page.waitForTimeout(150);
    }
    report.filteredCloudCount = await page.locator("[data-specimen-card]:visible").count();
    const telemetryTxt = await page.evaluate(() => document.body.innerText);
    report.telemetryUpdated = telemetryTxt.includes("18.5") || telemetryTxt.includes("88%");

    const allBtn = page.getByRole("button", { name: /^All\b/i }).first();
    if (await allBtn.count()) {
      await allBtn.click();
      await page.waitForTimeout(150);
    }
    report.resetAllCount = await page.locator("[data-specimen-card]:visible").count();

    // 4. Search empty state + reset
    const searchInput = page.locator("input[type='search']").first();
    if (await searchInput.count()) {
      await searchInput.fill("zzzz-nonexistent-flora");
      await page.waitForTimeout(150);
      report.emptySearchCount = await page.locator("[data-specimen-card]:visible").count();
      const emptyEl = page.locator("[data-empty-state]").first();
      report.emptyStateVisible = (await emptyEl.count()) > 0 && (await emptyEl.isVisible());
      const clearBtn = page.locator("[data-empty-state] button").first();
      if (await clearBtn.count()) {
        await clearBtn.click();
      } else {
        await searchInput.fill("");
      }
      await page.waitForTimeout(150);
    }
    report.afterSearchResetCount = await page.locator("[data-specimen-card]:visible").count();

    // 5. Specimen detail modal open + Escape close + focus return
    const firstTrigger = page.locator("[data-specimen-card]:visible button:not([data-compare-toggle]), button[data-specimen-card]:visible").first();
    if (await firstTrigger.count()) {
      await firstTrigger.evaluate((el) => { el.setAttribute("data-grader-focus-target", "1"); });
      await firstTrigger.focus();
      await firstTrigger.click();
      await page.waitForTimeout(200);
      const dialog = page.locator("dialog[open], [role='dialog']:visible").first();
      report.modalOpened = (await dialog.count()) > 0;
      report.modalHasLatin = report.modalOpened
        ? (await dialog.innerText()).includes("Nepenthes rajah")
        : false;
      if (report.modalOpened) {
        await page.screenshot({ path: path.join(PREVIEWS, "g6_desktop_modal.png"), fullPage: false });
        await page.keyboard.press("Escape");
        await page.waitForTimeout(150);
        report.modalClosedOnEscape = (await page.locator("dialog[open], [role='dialog']:visible").count()) === 0;
        report.modalFocusReturned = await page.evaluate(() => {
          const active = document.activeElement;
          return !!(active && active.getAttribute("data-grader-focus-target") === "1");
        });
      } else {
        report.modalClosedOnEscape = false;
        report.modalFocusReturned = false;
      }
    }

    // 6. Field Guide Comparison Drawer (select 2 specimens -> inspect side by side -> clear)
    let compareDrawerOk = false;
    const compareToggles = page.locator("[data-specimen-card]:visible [data-compare-toggle]");
    if ((await compareToggles.count()) >= 2) {
      await compareToggles.nth(0).click();
      await page.waitForTimeout(100);
      await compareToggles.nth(1).click();
      await page.waitForTimeout(150);
      const openBtn = page.locator("[data-compare-open]").first();
      if (await openBtn.count() && await openBtn.isVisible()) {
        await openBtn.click();
        await page.waitForTimeout(150);
      }
      const drawer = page.locator("[data-compare-drawer]").first();
      const drawerVisible = (await drawer.count()) > 0 && (await drawer.isVisible());
      const drawerTxt = drawerVisible ? await drawer.innerText() : "";
      const hasBoth = drawerTxt.includes("Giant Montane Pitcher") && drawerTxt.includes("Monkey-Face Orchid");
      const clearCmpBtn = drawer.locator("[data-compare-clear], button").filter({ hasText: /clear|reset/i }).first();
      let clearedOk = false;
      if (drawerVisible && (await clearCmpBtn.count())) {
        await clearCmpBtn.click();
        await page.waitForTimeout(150);
        const stillVis = await drawer.isVisible();
        const afterTxt = stillVis ? await drawer.innerText() : "";
        clearedOk = !stillVis || (!afterTxt.includes("Giant Montane Pitcher") && !afterTxt.includes("Monkey-Face Orchid"));
      }
      compareDrawerOk = drawerVisible && hasBoth && clearedOk;
    }
    report.compareDrawerOk = compareDrawerOk;

    // 7. Visit pass estimator form validation + computation
    const form = page.locator("form").first();
    if (await form.count()) {
      const dateIn = form.locator("input[type='date']").first();
      const numIn = form.locator("input[type='number']").first();
      const selIn = form.locator("select").first();
      const submitBtn = form.locator("button[type='submit']").first();

      if (await dateIn.count()) await dateIn.fill("");
      if (await numIn.count()) await numIn.fill("12");
      if (await submitBtn.count()) await submitBtn.click();
      await page.waitForTimeout(150);
      const alertText = await form.locator("[role='alert']").allInnerTexts();
      report.invalidFormShowsAlert = alertText.join(" ").trim().length > 0;

      if (await dateIn.count()) await dateIn.fill("2026-12-15");
      if (await numIn.count()) await numIn.fill("3");
      if (await selIn.count()) {
        const opts = await selIn.locator("option").allTextContents();
        const curIdx = opts.findIndex((t) => /Curator/i.test(t));
        if (curIdx >= 0) await selIn.selectOption({ index: curIdx });
      }
      if (await submitBtn.count()) await submitBtn.click();
      await page.waitForTimeout(150);
      const summary = await page.locator("[data-pass-summary]").allInnerTexts();
      report.validFormShowsTotal = summary.join(" ").includes("102");
    }

    // 8. Tablet 768x1024 overflow check + preview
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto(BASE_URL + "/index.html", { waitUntil: "networkidle" });
    await page.waitForTimeout(200);
    const tab = await page.evaluate(() => ({
      overflowTablet: document.documentElement.scrollWidth > window.innerWidth + 2,
      scrollWidthTablet: document.documentElement.scrollWidth,
      innerWidthTablet: window.innerWidth,
    }));
    Object.assign(report, tab);
    await page.screenshot({ path: path.join(PREVIEWS, "g6_tablet_768.png"), fullPage: false });

    // 9. Mobile 375x812 check + axe-core
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(BASE_URL + "/index.html", { waitUntil: "networkidle" });
    await page.waitForTimeout(250);
    const mob = await page.evaluate(() => ({
      overflowMobile: document.documentElement.scrollWidth > window.innerWidth + 2,
      scrollWidthMobile: document.documentElement.scrollWidth,
      innerWidthMobile: window.innerWidth,
    }));
    Object.assign(report, mob);
    await page.screenshot({ path: path.join(PREVIEWS, "g6_mobile_375.png"), fullPage: false });

    await page.addScriptTag({ content: axe.source });
    const axeMob = await page.evaluate(() =>
      window.axe.run({ runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] } })
    );
    report.axeMobileSevere = axeMob.violations
      .filter((v) => v.impact === "critical" || v.impact === "serious")
      .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));

    // 10. XSS injection safety check
    const xssPage = await context.newPage();
    await xssPage.goto(XSS_URL + "/index.html", { waitUntil: "networkidle" });
    await xssPage.waitForTimeout(250);
    const xssTrigger = xssPage.locator("[data-specimen-card] button:not([data-compare-toggle]), button[data-specimen-card]").first();
    if (await xssTrigger.count()) {
      await xssTrigger.click();
      await xssPage.waitForTimeout(200);
    }
    report.xssTriggered = await xssPage.evaluate(() => Boolean(window.__xss_triggered));
  } finally {
    await browser.close();
  }

  fs.writeFileSync(path.join(OUT_DIR, "audit_result.json"), JSON.stringify(report, null, 2));
}

runAudit().catch((err) => {
  fs.writeFileSync(path.join(OUT_DIR, "audit_error.txt"), String(err && err.stack ? err.stack : err));
  process.exit(1);
});
"""

CONTAINER_RUNNER = r"""
import functools
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import threading
from pathlib import Path

OUT_DIR = Path("/grade_out")
SITE = Path("/workspace/site")
XSS_SITE = Path("/tmp/xss_site")
if XSS_SITE.exists():
    shutil.rmtree(XSS_SITE)
shutil.copytree(SITE, XSS_SITE)

spec_file = XSS_SITE / "data" / "specimens.json"
if spec_file.is_file():
    data = json.loads(spec_file.read_text(encoding="utf-8"))
    if data.get("specimens"):
        payload = '<img src=x onerror="window.__xss_triggered=1">'
        data["specimens"][0]["summary"] = payload + " " + data["specimens"][0]["summary"]
        data["specimens"][0]["careNotes"] = payload + " " + data["specimens"][0]["careNotes"]
    spec_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def serve(directory: Path, port: int):
    handler = functools.partial(QuietHandler, directory=str(directory))
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


s1 = serve(SITE, 4173)
s2 = serve(XSS_SITE, 4174)
try:
    env = dict(os.environ)
    env["BASE_URL"] = "http://127.0.0.1:4173"
    env["XSS_URL"] = "http://127.0.0.1:4174"
    env["OUT_DIR"] = str(OUT_DIR)
    proc = subprocess.run(
        ["node", "/grade_scripts/audit.cjs"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"audit.cjs failed ({proc.returncode}): {proc.stdout}\n{proc.stderr}")
finally:
    s1.shutdown()
    s2.shutdown()
"""


def _scan_css(workspace: Path) -> dict[str, Any]:
    css_path = workspace / "site" / "styles.css"
    css = css_path.read_text(encoding="utf-8", errors="replace") if css_path.is_file() else ""
    var_names = set(re.findall(r"(--[a-z0-9-]+)\s*:", css, re.IGNORECASE))
    return {
        "has_tokens": bool(re.search(r":root\s*\{[^}]*--[a-z0-9-]+", css, re.IGNORECASE | re.DOTALL)),
        "css_custom_property_count": len(var_names),
        "has_responsive": bool(re.search(r"@(media|container)\s*\(", css)),
        "has_focus_visible": ":focus-visible" in css,
        "has_reduced_motion": "prefers-reduced-motion" in css,
    }


def grade(
    run_id: str,
    workspace: Path,
    deliverables: Path,
    task_dir: Path,
) -> GradeResult:
    _ = task_dir
    req = [
        workspace / "site" / "index.html",
        workspace / "site" / "styles.css",
        workspace / "site" / "app.js",
    ]
    if not all(p.is_file() for p in req):
        return GradeResult(
            run_id=run_id,
            task_id="G6-frontend-design",
            status="missing_deliverable",
            gates=GateResults(
                G1_CONTRACT_BUILD=False,
                G2_CRITICAL_CORRECTNESS=False,
                G3_CRITICAL_SAFETY_RULES=False,
            ),
        )

    css_meta = _scan_css(workspace)

    with tempfile.TemporaryDirectory(prefix="g6-grade-") as tmp:
        tdir = Path(tmp)
        audit_path = tdir / "audit.cjs"
        audit_path.write_text(AUDIT_MJS, encoding="utf-8")
        runner_path = tdir / "run_g6.py"
        runner_path.write_text(CONTAINER_RUNNER, encoding="utf-8")
        out_dir = tdir / "out"
        out_dir.mkdir()

        proc = run_in_sandbox(
            workspace,
            ["/opt/skilleval-py/bin/python", "/grade_scripts/run_g6.py"],
            extra_mounts={
                audit_path: "/grade_scripts/audit.cjs",
                runner_path: "/grade_scripts/run_g6.py",
            },
            output_dir=out_dir,
            timeout=150,
            network_none=True,
            link_node_modules=True,
        )
        res_file = out_dir / "audit_result.json"
        if proc.returncode != 0 or not res_file.is_file():
            err_txt = (out_dir / "audit_error.txt").read_text(encoding="utf-8") if (out_dir / "audit_error.txt").is_file() else ""
            return GradeResult(
                run_id=run_id,
                task_id="G6-frontend-design",
                status="grader_error",
                gates=GateResults(
                    G1_CONTRACT_BUILD=False,
                    G2_CRITICAL_CORRECTNESS=False,
                    G3_CRITICAL_SAFETY_RULES=False,
                ),
                error_detail=f"Audit failed ({proc.returncode}): {err_txt or proc.stderr[-600:]}",
            )
        data: dict[str, Any] = json.loads(res_file.read_text(encoding="utf-8"))

        deliv_prev = deliverables / "_grader_previews"
        deliv_prev.mkdir(parents=True, exist_ok=True)
        visual_previews: list[str] = []
        src_prev = out_dir / "_grader_previews"
        if src_prev.is_dir():
            for png in sorted(src_prev.glob("*.png")):
                dst = deliv_prev / png.name
                dst.write_bytes(png.read_bytes())
                visual_previews.append(f"deliverables/_grader_previews/{png.name}")

        dm = dict(data.get("designMetrics") or {})
        design_audit = {
            "body_bg_hex": dm.get("body_bg_hex"),
            "body_color_hex": dm.get("body_color_hex"),
            "body_font_family": dm.get("body_font_family"),
            "h1_font_family": dm.get("h1_font_family"),
            "h1_font_size_px": dm.get("h1_font_size_px"),
            "body_font_size_px": dm.get("body_font_size_px"),
            "h1_to_body_ratio": dm.get("h1_to_body_ratio"),
            "uppercase_label_count": dm.get("uppercase_label_count"),
            "middle_dot_count": dm.get("middle_dot_count"),
            "arrow_cta_count": dm.get("arrow_cta_count"),
            "em_dash_label_count": dm.get("em_dash_label_count"),
            "max_paragraph_width_px": dm.get("max_paragraph_width_px"),
            "submit_button_text": dm.get("submit_button_text"),
            "css_custom_property_count": css_meta["css_custom_property_count"],
            "has_focus_visible": css_meta["has_focus_visible"],
            "has_reduced_motion": css_meta["has_reduced_motion"],
            "has_responsive_rules": css_meta["has_responsive"],
            "overflow_1440": bool(data.get("overflowDesktop")),
            "overflow_768": bool(data.get("overflowTablet")),
            "overflow_375": bool(data.get("overflowMobile")),
            "modal_focus_returned": bool(data.get("modalFocusReturned")),
            "compare_drawer_ok": bool(data.get("compareDrawerOk")),
        }
        audit_summary_dir = deliverables / "_grader_summary"
        audit_summary_dir.mkdir(parents=True, exist_ok=True)
        (audit_summary_dir / "design_audit.json").write_text(
            json.dumps(design_audit, indent=2) + "\n", encoding="utf-8"
        )

    render_ok = (
        data.get("httpStatus") == 200
        and not data.get("pageErrors")
        and not data.get("consoleErrors")
        and int(data.get("cardCount", 0)) == 12
    )
    layout_ok = (
        (not data.get("overflowDesktop"))
        and (not data.get("overflowTablet"))
        and (not data.get("overflowMobile"))
    )
    filter_ok = (
        data.get("filteredCloudCount") == 4
        and bool(data.get("telemetryUpdated"))
        and data.get("resetAllCount") == 12
    )
    search_empty_ok = (
        data.get("emptySearchCount") == 0
        and bool(data.get("emptyStateVisible"))
        and data.get("afterSearchResetCount") == 12
    )
    modal_ok = (
        bool(data.get("modalOpened"))
        and bool(data.get("modalHasLatin"))
        and bool(data.get("modalClosedOnEscape"))
        and bool(data.get("modalFocusReturned"))
    )
    compare_ok = bool(data.get("compareDrawerOk"))
    form_ok = bool(data.get("invalidFormShowsAlert")) and bool(data.get("validFormShowsTotal"))
    landmarks_ok = (
        data.get("h1Count") == 1
        and bool(data.get("hasHeader"))
        and bool(data.get("hasMain"))
        and bool(data.get("hasNav"))
    )
    axe_ok = (
        len(data.get("axeDesktopSevere") or []) == 0
        and len(data.get("axeMobileSevere") or []) == 0
    )
    xss_safe_ok = not bool(data.get("xssTriggered"))
    offline_ok = len(data.get("externalRequests") or []) == 0
    css_polish_ok = (
        css_meta["has_tokens"]
        and css_meta["has_responsive"]
        and css_meta["has_focus_visible"]
        and css_meta["has_reduced_motion"]
    )

    g1_gate = render_ok and len(visual_previews) >= 2
    g2_gate = layout_ok and filter_ok and search_empty_ok and modal_ok and compare_ok and form_ok
    g3_gate = axe_ok and xss_safe_ok and offline_ok and landmarks_ok

    checks = [
        CheckOutcome(
            id="g6_renders_12_specimens_zero_errors",
            dimension="correctness_completeness",
            critical=True,
            passed=render_ok,
            detail=f"status={data.get('httpStatus')}, cards={data.get('cardCount')}, errs={data.get('pageErrors')}",
        ),
        CheckOutcome(
            id="g6_biome_filter_and_telemetry",
            dimension="correctness_completeness",
            critical=True,
            passed=filter_ok,
            detail=f"cloud={data.get('filteredCloudCount')}, telemetry={data.get('telemetryUpdated')}, reset={data.get('resetAllCount')}",
        ),
        CheckOutcome(
            id="g6_modal_compare_and_pass_estimator",
            dimension="correctness_completeness",
            critical=True,
            passed=modal_ok and compare_ok and form_ok,
            detail=(
                f"modal=({data.get('modalOpened')},{data.get('modalHasLatin')},{data.get('modalClosedOnEscape')},focus={data.get('modalFocusReturned')}), "
                f"compare={compare_ok}, form=({data.get('invalidFormShowsAlert')},{data.get('validFormShowsTotal')})"
            ),
        ),
        CheckOutcome(
            id="g6_responsive_zero_overflow_and_empty_state",
            dimension="robustness_edge_cases",
            critical=True,
            passed=layout_ok and search_empty_ok,
            detail=(
                f"overflow1440={data.get('overflowDesktop')}, overflow768={data.get('overflowTablet')}, "
                f"overflow375={data.get('overflowMobile')}, empty={search_empty_ok}"
            ),
        ),
        CheckOutcome(
            id="g6_wcag_axe_core_desktop_and_mobile",
            dimension="solution_performance_security",
            critical=True,
            passed=axe_ok and landmarks_ok,
            detail=f"axeD={data.get('axeDesktopSevere')}, axeM={data.get('axeMobileSevere')}, landmarks={landmarks_ok}",
        ),
        CheckOutcome(
            id="g6_xss_safe_and_offline_and_css_polish",
            dimension="solution_performance_security",
            critical=True,
            passed=xss_safe_ok and offline_ok and css_polish_ok,
            detail=f"xssTriggered={data.get('xssTriggered')}, extReq={data.get('externalRequests')}, css={css_meta}",
        ),
    ]

    return GradeResult(
        run_id=run_id,
        task_id="G6-frontend-design",
        status="graded",
        gates=GateResults(
            G1_CONTRACT_BUILD=g1_gate,
            G2_CRITICAL_CORRECTNESS=g2_gate,
            G3_CRITICAL_SAFETY_RULES=g3_gate,
        ),
        checks=checks,
        solution_performance={
            "axe_desktop_severe": len(data.get("axeDesktopSevere") or []),
            "axe_mobile_severe": len(data.get("axeMobileSevere") or []),
            "xss_triggered": bool(data.get("xssTriggered")),
            "css_meta": css_meta,
            "design_audit": design_audit,
        },
        visual_previews=visual_previews,
    )
