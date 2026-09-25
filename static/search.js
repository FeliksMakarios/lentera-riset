// Halaman hasil pencarian. Pertanyaan diambil dari kolom pencarian di kepala situs
// (?q=...). Jika Worker pencarian semantik aktif, pertanyaan diubah menjadi vektor
// makna oleh Worker, lalu dibandingkan dengan vektor setiap makalah di
// search-index.json (kemiripan kosinus). Jika tidak, hasil memakai kecocokan kata kunci.
(function () {
  var L = window.Lentera;
  var results = document.getElementById("search-results");
  if (!L || !results) return;

  var status = document.getElementById("search-status");
  var title = document.getElementById("search-title");
  var headerInput = document.getElementById("site-q");
  var selWaktu = document.getElementById("filter-waktu");
  var selTopik = document.getElementById("filter-topik");
  var selBahasa = document.getElementById("filter-bahasa");
  var worker = (document.body.dataset.worker || "").replace(/\/+$/, "");
  var MAX_RESULTS = 30;
  var STOPWORDS = ("a an and are as at be by for from in into is of on or the to with " +
    "yang dan di ke dari untuk pada dengan dalam atau ini itu adalah sebagai oleh bahasa").split(" ");

  var params = L.params();
  var query = (params.get("q") || "").trim().slice(0, 300);
  headerInput.value = query;
  selWaktu.value = params.get("waktu") || "";
  selTopik.value = params.get("topik") || "";

  function setStatus(text) { status.textContent = text; }

  function fillLanguages(catalog, selected) {
    Object.keys(catalog.language_groups).forEach(function (g) {
      var og = document.createElement("optgroup");
      og.label = catalog.language_groups[g];
      Object.keys(catalog.languages).forEach(function (id) {
        var lang = catalog.languages[id];
        if (lang.group !== g) return;
        var opt = document.createElement("option");
        opt.value = id;
        opt.textContent = lang.name + " (" + lang.count + ")";
        og.appendChild(opt);
      });
      if (og.children.length) selBahasa.appendChild(og);
    });
    selBahasa.value = selected;
  }

  function decode(b64) {
    var bin = atob(b64);
    var vec = new Int8Array(bin.length);
    var norm = 0;
    for (var i = 0; i < bin.length; i++) {
      var x = bin.charCodeAt(i);
      vec[i] = x > 127 ? x - 256 : x;
      norm += vec[i] * vec[i];
    }
    return { vec: vec, norm: Math.sqrt(norm) || 1 };
  }

  function cacheGet(key) {
    try { return JSON.parse(sessionStorage.getItem(key) || "null"); } catch (e) { return null; }
  }
  function cacheSet(key, value) {
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* abaikan */ }
  }

  // Minta vektor pertanyaan dari Worker; hasilnya disimpan selama sesi peramban.
  function embedQuery(index) {
    var key = "lentera:q:" + index.model + ":" + index.dimensions + ":" + query.toLowerCase();
    var cached = cacheGet(key);
    if (cached) return Promise.resolve(cached);
    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 15000) : null;
    return fetch(worker + "/embed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: query }),
      signal: controller ? controller.signal : undefined
    }).then(function (r) {
      if (timer) clearTimeout(timer);
      if (r.status === 429) throw new Error("terlalu banyak permintaan, coba lagi sebentar lagi");
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (data) {
      if (data.model !== index.model || data.dimensions !== index.dimensions) {
        throw new Error("model Worker berbeda dengan indeks");
      }
      cacheSet(key, data.embedding);
      return data.embedding;
    });
  }

  function passes(p) {
    if (selTopik.value && p.topics.indexOf(selTopik.value) === -1) return false;
    if (selBahasa.value && p.languages.indexOf(selBahasa.value) === -1) return false;
    if (selWaktu.value) {
      var cutoff = Date.now() - parseInt(selWaktu.value, 10) * 86400000;
      if (new Date(p.date).getTime() < cutoff) return false;
    }
    return true;
  }

  function semanticRank(catalog, vectors, q) {
    var qn = Math.sqrt(q.reduce(function (s, x) { return s + x * x; }, 0)) || 1;
    var scored = [];
    catalog.papers.forEach(function (p) {
      var v = vectors[p.id];
      if (!v || !passes(p)) return;
      var dot = 0;
      for (var i = 0; i < v.vec.length; i++) dot += v.vec[i] * q[i];
      scored.push({ paper: p, sim: dot / (v.norm * qn) });
    });
    scored.sort(function (a, b) { return b.sim - a.sim; });
    return scored.slice(0, MAX_RESULTS);
  }

  function keywordRank(catalog) {
    var words = query.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(function (t) {
      return t.length > 1 && STOPWORDS.indexOf(t) === -1;
    });
    if (!words.length) words = [query.toLowerCase()];
    var scored = [];
    catalog.papers.forEach(function (p) {
      if (!passes(p)) return;
      var t = p.title.toLowerCase();
      var a = p.authors.toLowerCase();
      var rest = [p.tldr, p.tldr_en, p.snippet].concat(p.languages.map(function (l) {
        return catalog.languages[l] ? catalog.languages[l].name : "";
      })).join(" ").toLowerCase();
      var score = 0;
      words.forEach(function (w) {
        if (t.indexOf(w) !== -1) score += 3;
        if (a.indexOf(w) !== -1) score += 2;
        if (rest.indexOf(w) !== -1) score += 1;
      });
      if (score) scored.push({ paper: p, score: score });
    });
    scored.sort(function (x, y) { return y.score - x.score || y.paper.score - x.paper.score; });
    return scored.slice(0, MAX_RESULTS);
  }

  var catalog = null;
  var vectors = null;
  var queryVector = null;
  var mode = null;
  var note = "";

  function render() {
    var items = mode === "semantic" ? semanticRank(catalog, vectors, queryVector) : keywordRank(catalog);
    results.innerHTML = "";
    items.forEach(function (item) {
      results.appendChild(L.renderCard(item.paper, catalog, mode === "semantic" ? { similarity: item.sim } : {}));
    });
    var summary = items.length
      ? (mode === "semantic"
        ? items.length + " makalah yang maknanya paling dekat dengan pencarian Anda."
        : items.length + " makalah yang memuat kata pencarian Anda.")
      : "Tidak ada makalah yang cocok. Coba longgarkan saringan.";
    setStatus(note ? note + " " + summary : summary);
    var p = new URLSearchParams();
    p.set("q", query);
    if (selWaktu.value) p.set("waktu", selWaktu.value);
    if (selTopik.value) p.set("topik", selTopik.value);
    if (selBahasa.value) p.set("bahasa", selBahasa.value);
    L.setParams(p);
  }

  [selWaktu, selTopik, selBahasa].forEach(function (sel) {
    sel.addEventListener("change", function () { if (catalog && mode) render(); });
  });

  if (!query) {
    title.textContent = "Cari makalah";
    setStatus("Tulis topik atau pertanyaan di kolom pencarian di bagian atas halaman, lalu tekan Enter.");
    headerInput.focus();
    L.loadJSON("catalog.json").then(function (c) { fillLanguages(c, params.get("bahasa") || ""); });
    return;
  }

  title.textContent = "Hasil pencarian untuk “" + query + "”";
  document.title = query + " | " + document.title;
  setStatus("Mencari...");

  Promise.all([L.loadJSON("catalog.json"), L.loadJSON("search-index.json").catch(function () { return null; })])
    .then(function (loaded) {
      catalog = loaded[0];
      fillLanguages(catalog, params.get("bahasa") || "");
      var index = loaded[1];
      if (!worker || !index || !Object.keys(index.vectors).length) {
        mode = "keyword";
        note = "Pencarian semantik belum aktif, jadi hasil memakai kecocokan kata kunci.";
        return;
      }
      vectors = {};
      Object.keys(index.vectors).forEach(function (id) { vectors[id] = decode(index.vectors[id]); });
      return embedQuery(index).then(function (q) {
        queryVector = q;
        mode = "semantic";
      }).catch(function (err) {
        var reason = err.name === "AbortError" ? "waktu tunggu habis"
          : err instanceof TypeError ? "Worker tidak bisa dihubungi" : err.message;
        mode = "keyword";
        note = "Pencarian semantik sedang tidak bisa dipakai (" + reason + "), jadi hasil memakai kecocokan kata kunci.";
      });
    })
    .then(render)
    .catch(function (err) {
      setStatus("Indeks pencarian gagal dimuat (" + err.message + "). Coba muat ulang halaman.");
    });
})();
