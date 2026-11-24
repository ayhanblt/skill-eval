fetch("./data/specimens.json")
  .then((r) => r.json())
  .then((d) => {
    const host = document.getElementById("cards");
    for (const s of d.specimens) {
      const el = document.createElement("article");
      el.setAttribute("data-specimen-card", s.id);
      const h = document.createElement("h2");
      h.textContent = s.commonName;
      el.appendChild(h);
      host.appendChild(el);
    }
  });
