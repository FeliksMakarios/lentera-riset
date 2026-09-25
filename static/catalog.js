// Halaman Makalah: seluruh koleksi dengan saringan Tugas, Topik, dan Bahasa di panel
// kiri (seperti halaman Models di Hugging Face), saringan judul, urutan, dan halaman.
(function () {
  var L = window.Lentera;
  var list = document.getElementById("catalog-list");
  if (!L || !list) return;

  var facetFilter = document.getElementById("facet-filter");
  var facetList = document.getElementById("facet-list");
  var facetTabs = Array.prototype.slice.call(document.querySelectorAll(".facet-tab"));
  var qInput = document.getElementById("catalog-q");
  var sortSelect = document.getElementById("catalog-sort");
  var count = document.getElementById("catalog-count");
  var activeBox = document.getElementById("active-filters");
  var pager = document.getElementById("catalog-pager");
  var PER_PAGE = parseInt(list.dataset.perPage, 10) || 20;
  var FACETS = {
    tugas: { field: "tasks", label: "Tugas", placeholder: "Saring tugas berdasarkan nama" },
    topik: { field: "topics", label: "Topik", placeholder: "Saring topik berdasarkan nama" },
    bahasa: { field: "languages", label: "Bahasa", placeholder: "Saring bahasa berdasarkan nama" }
  };

  var catalog = null;
  var state = { facet: "tugas", tugas: "", topik: "", bahasa: "", q: "", urut: "ramai", hal: 1 };

  function readParams() {
    var p = L.params();
    ["tugas", "topik", "bahasa", "q"].forEach(function (k) { state[k] = p.get(k) || ""; });
    state.urut = p.get("urut") || "ramai";
    state.hal = parseInt(p.get("hal"), 10) || 1;
    state.facet = state.bahasa ? "bahasa" : state.topik ? "topik" : "tugas";
    if (p.get("panel") && FACETS[p.get("panel")]) state.facet = p.get("panel");
  }

  function writeParams() {
    var p = new URLSearchParams();
    ["tugas", "topik", "bahasa", "q"].forEach(function (k) { if (state[k]) p.set(k, state[k]); });
    if (state.urut !== "ramai") p.set("urut", state.urut);
    if (state.hal > 1) p.set("hal", state.hal);
    L.setParams(p);
  }

  // Pilihan untuk satu kategori: {id, name, group, count}. Jumlahnya dihitung dari
  // makalah yang lolos saringan lain, jadi pilihan yang tidak menghasilkan apa pun
  // tidak ditampilkan (kecuali yang sedang dipilih).
  function options(facet) {
    var field = FACETS[facet].field;
    var counts = {};
    matching(facet).forEach(function (p) {
      p[field].forEach(function (id) { counts[id] = (counts[id] || 0) + 1; });
    });
    var ids = facet === "topik" ? Object.keys(catalog.topics)
      : Object.keys(facet === "tugas" ? catalog.tasks : catalog.languages);
    return ids.filter(function (id) { return counts[id] || state[facet] === id; }).map(function (id) {
      var info = facet === "tugas" ? catalog.tasks[id] : facet === "bahasa" ? catalog.languages[id] : null;
      return { id: id, name: nameOf(facet, id), group: info ? info.group : "", count: counts[id] || 0 };
    });
  }

  function groupLabels(facet) {
    if (facet === "tugas") return catalog.task_groups || {};
    if (facet === "bahasa") return catalog.language_groups || {};
    return { "": "" };
  }

  function nameOf(facet, id) {
    if (facet === "topik") return catalog.topics[id] || id;
    var source = facet === "tugas" ? catalog.tasks : catalog.languages;
    return source[id] ? source[id].name : id;
  }

  function renderFacets() {
    facetTabs.forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.dataset.facet === state.facet ? "true" : "false");
    });
    facetFilter.placeholder = FACETS[state.facet].placeholder;
    var needle = facetFilter.value.trim().toLowerCase();
    var opts = options(state.facet).filter(function (o) {
      return !needle || o.name.toLowerCase().indexOf(needle) !== -1;
    });
    facetList.innerHTML = "";
    var labels = groupLabels(state.facet);
    Object.keys(labels).forEach(function (g) {
      var members = opts.filter(function (o) { return (o.group || "") === g || (g === "" && !labels[o.group]); });
      if (state.facet !== "topik") members.sort(function (a, b) { return b.count - a.count || a.name.localeCompare(b.name); });
      if (!members.length) return;
      if (labels[g]) facetList.appendChild(L.el("h3", "facet-group", labels[g]));
      var box = L.el("div", "facet-chips");
      members.forEach(function (o) {
        var chip = L.el("button", "facet-chip");
        chip.type = "button";
        chip.appendChild(document.createTextNode(o.name + " "));
        chip.appendChild(L.el("span", "chip-count", String(o.count)));
        var selected = state[state.facet] === o.id;
        chip.setAttribute("aria-pressed", selected ? "true" : "false");
        chip.addEventListener("click", function () {
          state[state.facet] = selected ? "" : o.id;
          state.hal = 1;
          update();
        });
        box.appendChild(chip);
      });
      facetList.appendChild(box);
    });
    if (!facetList.children.length) facetList.appendChild(L.el("p", "note", "Tidak ada pilihan yang cocok."));
  }

  function renderActive() {
    activeBox.innerHTML = "";
    var any = false;
    Object.keys(FACETS).forEach(function (f) {
      if (!state[f]) return;
      any = true;
      var chip = L.el("button", "active-chip");
      chip.type = "button";
      chip.textContent = FACETS[f].label + ": " + nameOf(f, state[f]) + " ×";
      chip.setAttribute("aria-label", "Hapus saringan " + FACETS[f].label);
      chip.addEventListener("click", function () { state[f] = ""; state.hal = 1; update(); });
      activeBox.appendChild(chip);
    });
    if (any) {
      var clear = L.el("button", "link-button", "Hapus semua saringan");
      clear.type = "button";
      clear.addEventListener("click", function () {
        state.tugas = state.topik = state.bahasa = "";
        state.hal = 1;
        update();
      });
      activeBox.appendChild(clear);
    }
  }

  // Makalah yang lolos semua saringan, kecuali kategori `except` (untuk menghitung pilihan).
  function matching(except) {
    var words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    var papers = catalog.papers.filter(function (p) {
      if (except !== "tugas" && state.tugas && p.tasks.indexOf(state.tugas) === -1) return false;
      if (except !== "topik" && state.topik && p.topics.indexOf(state.topik) === -1) return false;
      if (except !== "bahasa" && state.bahasa && p.languages.indexOf(state.bahasa) === -1) return false;
      if (!words.length) return true;
      var text = (p.title + " " + p.authors).toLowerCase();
      return words.every(function (w) { return text.indexOf(w) !== -1; });
    });
    papers.sort(function (a, b) {
      if (state.urut === "terbaru") return b.date.localeCompare(a.date) || b.score - a.score;
      if (state.urut === "judul") return a.title.localeCompare(b.title);
      return b.score - a.score;
    });
    return papers;
  }

  function row(p) {
    var item = L.el("article", "row");
    var title = L.el("a", "row-title", p.title);
    title.href = L.root + p.url;
    item.appendChild(title);
    var meta = L.el("div", "row-meta");
    var parts = [];
    if (p.tasks.length) parts.push(p.tasks.slice(0, 2).map(function (t) { return nameOf("tugas", t); }).join(", "));
    parts.push(p.date_label);
    parts.push(p.source);
    if (p.languages.length) parts.push(p.languages.slice(0, 3).map(function (l) { return nameOf("bahasa", l); }).join(", "));
    parts.forEach(function (text, i) {
      if (i) meta.appendChild(L.el("span", "dot", "·"));
      meta.appendChild(L.el("span", i === 0 && p.tasks.length ? "row-task" : "", text));
    });
    item.appendChild(meta);
    item.appendChild(L.el("p", "row-authors", p.authors));
    return item;
  }

  function renderList() {
    var papers = matching();
    var pages = Math.max(1, Math.ceil(papers.length / PER_PAGE));
    state.hal = Math.min(state.hal, pages);
    count.textContent = papers.length;
    list.innerHTML = "";
    if (!papers.length) list.appendChild(L.el("p", "empty", "Tidak ada makalah yang cocok dengan saringan ini."));
    papers.slice((state.hal - 1) * PER_PAGE, state.hal * PER_PAGE).forEach(function (p) {
      list.appendChild(row(p));
    });
    L.renderPager(pager, state.hal, pages, function (n) {
      state.hal = n;
      update();
      document.querySelector(".catalog-main").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function update() {
    renderFacets();
    renderActive();
    renderList();
    writeParams();
  }

  facetTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      state.facet = tab.dataset.facet;
      facetFilter.value = "";
      renderFacets();
    });
  });
  facetFilter.addEventListener("input", renderFacets);
  var timer = null;
  qInput.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { state.q = qInput.value.trim(); state.hal = 1; update(); }, 150);
  });
  sortSelect.addEventListener("change", function () { state.urut = sortSelect.value; state.hal = 1; update(); });

  readParams();
  qInput.value = state.q;
  sortSelect.value = state.urut;
  L.loadJSON("catalog.json").then(function (data) {
    catalog = data;
    update();
  }).catch(function (err) {
    list.innerHTML = "";
    list.appendChild(L.el("p", "empty", "Daftar makalah gagal dimuat (" + err.message + "). Coba muat ulang halaman."));
  });
})();
