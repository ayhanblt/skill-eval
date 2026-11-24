(() => {
  const MAX_COMPARE = 3;
  const state = {
    data: null,
    biome: "All",
    query: "",
    bloom: "All",
    compareIds: [],
    lastTrigger: null,
  };

  const gridEl = document.getElementById("specimen-grid");
  const emptyEl = document.getElementById("empty-state");
  const searchEl = document.getElementById("specimen-search");
  const bloomEl = document.getElementById("bloom-filter");
  const resetBtn = document.getElementById("reset-filters-btn");
  const dialogEl = document.getElementById("specimen-dialog");
  const closeBtn = document.getElementById("dialog-close");
  const compareDrawerEl = document.getElementById("compare-drawer");
  const compareSlotsEl = document.getElementById("compare-slots");
  const compareStatusEl = document.getElementById("compare-status");
  const compareClearBtn = document.getElementById("compare-clear-btn");
  const formEl = document.getElementById("pass-form");
  const tierSelectEl = document.getElementById("pass-tier");
  const errorEl = document.getElementById("pass-error");
  const summaryEl = document.getElementById("pass-summary");

  function cleanSeparator(text) {
    return String(text || "").replace(/\s*\u00b7\s*/g, ", ");
  }

  function updateTelemetry() {
    if (!state.data) return;
    const biomeEl = document.getElementById("telemetry-biome");
    const tempEl = document.getElementById("telemetry-temp");
    const humEl = document.getElementById("telemetry-humidity");
    const mistEl = document.getElementById("telemetry-misting");
    const noteEl = document.getElementById("telemetry-note");

    if (state.biome === "All") {
      biomeEl.textContent = "All Biomes";
      tempEl.textContent = "7.5°C – 29.0°C";
      humEl.textContent = "24% – 88% RH";
      mistEl.textContent = "Microclimate scheduled";
      noteEl.textContent = "Select a pavilion to inspect real-time misting, thermal mass, and geothermal cooling conditions.";
      return;
    }

    const match = state.data.biomes.find((b) => b.id === state.biome);
    if (match) {
      biomeEl.textContent = match.id;
      tempEl.textContent = match.temperature_c;
      humEl.textContent = match.humidity_pct;
      mistEl.textContent = cleanSeparator(match.misting_schedule);
      noteEl.textContent = match.architectural_note;
    }
  }

  function renderCompareDrawer() {
    if (!state.data) return;
    const selected = state.compareIds
      .map((id) => state.data.specimens.find((s) => s.id === id))
      .filter(Boolean);

    compareSlotsEl.textContent = "";
    if (selected.length === 0) {
      compareDrawerEl.hidden = true;
      compareStatusEl.textContent = "0 of 3 specimens pinned for side-by-side review.";
      return;
    }

    compareDrawerEl.hidden = false;
    compareStatusEl.textContent = `${selected.length} of ${MAX_COMPARE} specimens pinned for side-by-side study.`;

    const frag = document.createDocumentFragment();
    for (const item of selected) {
      const box = document.createElement("article");
      box.className = "compare-card";

      const heading = document.createElement("h3");
      heading.textContent = item.commonName;

      const latin = document.createElement("p");
      latin.className = "latin-name";
      latin.textContent = item.latinName;

      const meta = document.createElement("dl");
      meta.className = "compare-meta";
      for (const [label, val] of [
        ["Biome", item.biome],
        ["Elevation", item.elevation],
        ["Bloom season", item.bloomSeason],
        ["Conservation", item.conservation],
      ]) {
        const row = document.createElement("div");
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = val;
        row.append(dt, dd);
        meta.appendChild(row);
      }

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "compare-btn";
      removeBtn.textContent = "Remove specimen";
      removeBtn.addEventListener("click", () => toggleCompare(item.id));

      box.append(heading, latin, meta, removeBtn);
      frag.appendChild(box);
    }
    compareSlotsEl.appendChild(frag);
  }

  function toggleCompare(specimenId) {
    const idx = state.compareIds.indexOf(specimenId);
    if (idx >= 0) {
      state.compareIds.splice(idx, 1);
    } else {
      if (state.compareIds.length >= MAX_COMPARE) {
        state.compareIds.shift();
      }
      state.compareIds.push(specimenId);
    }
    renderCompareDrawer();
    renderSpecimens();
  }

  function openSpecimenDialog(specimen, triggerEl) {
    state.lastTrigger = triggerEl;
    document.getElementById("dialog-biome").textContent = specimen.biome;
    document.getElementById("dialog-title").textContent = specimen.commonName;
    document.getElementById("dialog-latin").textContent = specimen.latinName;
    document.getElementById("dialog-elevation").textContent = specimen.elevation;
    document.getElementById("dialog-bloom").textContent = specimen.bloomSeason;
    document.getElementById("dialog-conservation").textContent = specimen.conservation;
    document.getElementById("dialog-summary").textContent = specimen.summary;
    document.getElementById("dialog-care").textContent = specimen.careNotes;
    dialogEl.showModal();
    closeBtn.focus();
  }

  function closeDialog() {
    if (dialogEl.open) {
      dialogEl.close();
    }
    if (state.lastTrigger && typeof state.lastTrigger.focus === "function") {
      state.lastTrigger.focus();
    }
  }

  function renderSpecimens() {
    if (!state.data) return;
    const q = state.query.trim().toLowerCase();
    const visible = state.data.specimens.filter((item) => {
      if (state.biome !== "All" && item.biome !== state.biome) return false;
      if (state.bloom !== "All" && item.bloomSeason !== state.bloom) return false;
      if (q) {
        const hay = `${item.commonName} ${item.latinName} ${item.summary} ${item.biome}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    gridEl.textContent = "";
    if (visible.length === 0) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;

    const frag = document.createDocumentFragment();
    for (const item of visible) {
      const card = document.createElement("article");
      card.className = "specimen-card";
      card.setAttribute("data-specimen-card", item.id);

      const top = document.createElement("div");
      const kicker = document.createElement("p");
      kicker.className = "specimen-biome";
      kicker.textContent = item.biome;

      const title = document.createElement("h3");
      title.textContent = item.commonName;

      const latin = document.createElement("p");
      latin.className = "latin-name";
      latin.textContent = item.latinName;

      const sum = document.createElement("p");
      sum.className = "specimen-summary";
      sum.textContent = item.summary;

      top.append(kicker, title, latin, sum);

      const footer = document.createElement("div");
      footer.className = "card-footer";
      const bloom = document.createElement("span");
      bloom.className = "bloom-tag";
      bloom.textContent = `Bloom season: ${item.bloomSeason}`;

      const actions = document.createElement("div");
      actions.className = "card-actions";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "inspect-btn";
      btn.textContent = "Inspect dossier";
      btn.setAttribute("aria-label", `Inspect ${item.commonName} (${item.latinName})`);
      btn.addEventListener("click", () => openSpecimenDialog(item, btn));

      const isCompared = state.compareIds.includes(item.id);
      const cmpBtn = document.createElement("button");
      cmpBtn.type = "button";
      cmpBtn.className = "compare-btn";
      cmpBtn.setAttribute("data-compare-toggle", item.id);
      cmpBtn.setAttribute("aria-pressed", isCompared ? "true" : "false");
      cmpBtn.setAttribute("aria-label", `${isCompared ? "Remove" : "Add"} ${item.commonName} comparison`);
      cmpBtn.textContent = isCompared ? "Pinned to guide" : "Add to field guide";
      cmpBtn.addEventListener("click", () => toggleCompare(item.id));

      actions.append(btn, cmpBtn);
      footer.append(bloom, actions);
      card.append(top, footer);
      frag.appendChild(card);
    }
    gridEl.appendChild(frag);
  }

  function populateTiers() {
    if (!state.data) return;
    tierSelectEl.textContent = "";
    for (const tier of state.data.visitPasses) {
      const opt = document.createElement("option");
      opt.value = tier.id;
      opt.textContent = `${tier.name} ($${tier.priceUsd})`;
      tierSelectEl.appendChild(opt);
    }
  }

  function wireEvents() {
    for (const btn of document.querySelectorAll(".filter-btn")) {
      btn.addEventListener("click", () => {
        state.biome = btn.dataset.biome || "All";
        for (const other of document.querySelectorAll(".filter-btn")) {
          const active = other === btn;
          other.classList.toggle("active", active);
          other.setAttribute("aria-pressed", active ? "true" : "false");
        }
        updateTelemetry();
        renderSpecimens();
      });
    }

    searchEl.addEventListener("input", () => {
      state.query = searchEl.value;
      renderSpecimens();
    });

    bloomEl.addEventListener("change", () => {
      state.bloom = bloomEl.value;
      renderSpecimens();
    });

    resetBtn.addEventListener("click", () => {
      state.biome = "All";
      state.query = "";
      state.bloom = "All";
      searchEl.value = "";
      bloomEl.value = "All";
      for (const btn of document.querySelectorAll(".filter-btn")) {
        const active = btn.dataset.biome === "All";
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      }
      updateTelemetry();
      renderSpecimens();
    });

    compareClearBtn.addEventListener("click", () => {
      state.compareIds = [];
      renderCompareDrawer();
      renderSpecimens();
    });

    closeBtn.addEventListener("click", closeDialog);
    dialogEl.addEventListener("cancel", (ev) => {
      ev.preventDefault();
      closeDialog();
    });

    formEl.addEventListener("submit", (ev) => {
      ev.preventDefault();
      errorEl.hidden = true;
      summaryEl.hidden = true;

      const dateVal = document.getElementById("visit-date").value.trim();
      const countVal = Number(document.getElementById("visitor-count").value);
      const tier = state.data.visitPasses.find((t) => t.id === tierSelectEl.value);

      if (!dateVal) {
        errorEl.textContent = "Choose a preferred visit date to calculate pass pricing.";
        errorEl.hidden = false;
        return;
      }
      if (!Number.isInteger(countVal) || countVal < 1 || countVal > 8) {
        errorEl.textContent = "Enter a whole visitor count between 1 and 8.";
        errorEl.hidden = false;
        return;
      }
      if (!tier) {
        errorEl.textContent = "Choose a conservatory pass tier before calculating.";
        errorEl.hidden = false;
        return;
      }

      const total = countVal * tier.priceUsd;
      summaryEl.textContent = `${tier.name} reserved for ${countVal} visitor(s) on ${dateVal}. Estimated total: $${total}.`;
      summaryEl.hidden = false;
    });
  }

  async function init() {
    const res = await fetch("./data/specimens.json");
    state.data = await res.json();
    populateTiers();
    wireEvents();
    updateTelemetry();
    renderCompareDrawer();
    renderSpecimens();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
