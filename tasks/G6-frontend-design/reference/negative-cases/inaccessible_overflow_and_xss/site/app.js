fetch("./data/specimens.json")
  .then((r) => r.json())
  .then((d) => {
    const grid = document.getElementById("grid");
    grid.innerHTML = d.specimens
      .map((s) => `<div data-specimen-card><h3>${s.commonName}</h3><p>${s.summary}</p></div>`)
      .join("");
  });
