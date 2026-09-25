// Halaman pencarian. Jika Worker pencarian semantik aktif, pertanyaan diubah menjadi
// vektor makna oleh Worker, lalu dibandingkan dengan vektor setiap makalah di
// search-index.json (kemiripan kosinus). Jika tidak, hasil memakai kecocokan kata kunci.
(function () {
  var form = document.getElementById("search-form");
  if (!form) return;

  var input = document.getElementById("q");
  var topicSelect = document.getElementById("search-topic");
  var langSelect = document.getElementById("search-language");
  var status = document.getElementById("search-status");
  var results = document.getElementById("search-results");
  var worker = (form.dataset.worker || "").replace(/\/+$/, "");
  var MAX_RESULTS = 30;
  var index = null;
  var loading = null;

  var STOPWORDS = ("a an and are as at be by for from in into is of on or the to with " +
    "yang dan di ke dari untuk pada dengan dalam atau ini itu adalah sebagai oleh bahasa").split(" ");

  function setStatus(text) { status.textContent = text; }

  function loadIndex() {
    if (!loading) {
      loading = fetch("search-index.json")
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (data) {
          data.papers.forEach(function (p) {
            if (!p.v) return;
            var bin = atob(p.v);
            var vec = new Int8Array(bin.length);
            var norm = 0;
            for (var i = 0; i < bin.length; i++) {
              var x = bin.charCodeAt(i);
              vec[i] = x > 127 ? x - 256 : x;
              norm += vec[i] * vec[i];
            }
            p.vec = vec;
            p.norm = Math.sqrt(norm) || 1;
          });
          index = data;
          fillLanguages(data.languages);
          return data;
        });
    }
    return loading;
  }

  function fillLanguages(languages) {
    var groups = { indonesia: "Indonesia dan daerah", austronesia: "Austronesia lainnya", other: "Bahasa lain" };
    var selected = langSelect.dataset.initial || "";
    Object.keys(groups).forEach(function (g) {
      var og = document.createElement("optgroup");
      og.label = groups[g];
      Object.keys(languages).forEach(function (id) {
        var lang = languages[id];
        if (lang.group !== g) return;
        var opt = document.createElement("option");
        opt.value = id;
        opt.textContent = lang.name + " (" + lang.count + ")";
        og.appendChild(opt);
      });
      if (og.children.length) langSelect.appendChild(og);
    });
    langSelect.value = selected;
    langSelect.dataset.initial = "";
  }

  function cacheGet(key) {
    try { return JSON.parse(sessionStorage.getItem(key) || "null"); } catch (e) { return null; }
  }
  function cacheSet(key, value) {
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* abaikan */ }
  }

  // Minta vektor pertanyaan dari Worker. Hasilnya disimpan selama sesi peramban.
  function embedQuery(text) {
    var key = "lentera:q:" + index.model + ":" + index.dimensions + ":" + text.toLowerCase();
    var cached = cacheGet(key);
    if (cached) return Promise.resolve(cached);
    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 15000) : null;
    return fetch(worker + "/embed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
      signal: controller ? controller.signal : undefined
    })
      .then(function (r) {
        if (timer) clearTimeout(timer);
        if (r.status === 429) throw new Error("terlalu banyak permintaan");
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (data.model !== index.model || data.dimensions !== index.dimensions) {
          throw new Error("model Worker (" + data.model + ") berbeda dengan indeks (" + index.model + ")");
        }
        cacheSet(key, data.embedding);
        return data.embedding;
      });
  }

  function passesFilters(p, topic, lang) {
    return (!topic || p.topics.indexOf(topic) !== -1) && (!lang || p.languages.indexOf(lang) !== -1);
  }

  function semanticRank(query, topic, lang) {
    var norm = 0;
    query.forEach(function (x) { norm += x * x; });
    norm = Math.sqrt(norm) || 1;
    var scored = [];
    index.papers.forEach(function (p) {
      if (!p.vec || !passesFilters(p, topic, lang)) return;
      var dot = 0;
      for (var i = 0; i < p.vec.length; i++) dot += p.vec[i] * query[i];
      scored.push({ paper: p, sim: dot / (p.norm * norm) });
    });
    scored.sort(function (a, b) { return b.sim - a.sim; });
    return scored.slice(0, MAX_RESULTS);
  }

  function terms(text) {
    return text.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(function (t) {
      return t.length > 1 && STOPWORDS.indexOf(t) === -1;
    });
  }

  function keywordRank(text, topic, lang) {
    var words = terms(text);
    if (!words.length) words = text.toLowerCase().split(/\s+/).filter(Boolean);
    var scored = [];
    index.papers.forEach(function (p) {
      if (!passesFilters(p, topic, lang)) return;
      var title = p.title.toLowerCase();
      var authors = p.authors.toLowerCase();
      var body = (p.tldr + " " + p.abstract + " " + p.languages.map(function (id) {
        return index.languages[id] ? index.languages[id].name : "";
      }).join(" ")).toLowerCase();
      var score = 0;
      words.forEach(function (w) {
        if (title.indexOf(w) !== -1) score += 3;
        if (authors.indexOf(w) !== -1) score += 2;
        if (body.indexOf(w) !== -1) score += 1;
      });
      if (score > 0) scored.push({ paper: p, score: score });
    });
    scored.sort(function (a, b) { return b.score - a.score || b.paper.score - a.paper.score; });
    return scored.slice(0, MAX_RESULTS);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function render(items, semantic) {
    results.innerHTML = "";
    items.forEach(function (item) {
      var p = item.paper;
      var card = el("article", "card");
      var meta = el("div", "card-meta");
      var time = el("time", "", p.date_label);
      time.setAttribute("datetime", p.date);
      meta.appendChild(time);
      meta.appendChild(el("span", "", p.source));
      p.topics.forEach(function (t) {
        if (!index.topics[t]) return;
        var chip = el("a", "chip chip-" + t, index.topics[t]);
        chip.href = "topik/" + t + ".html";
        meta.appendChild(chip);
      });
      if (semantic) {
        var badge = el("span", "match", "kemiripan " + Math.round(item.sim * 100) + "%");
        meta.appendChild(badge);
      }
      card.appendChild(meta);
      var h2 = el("h2");
      var link = el("a", "", p.title);
      link.href = p.url;
      h2.appendChild(link);
      card.appendChild(h2);
      card.appendChild(el("p", "authors", p.authors));
      var text = p.tldr || (p.abstract.length > 280 ? p.abstract.slice(0, 280).replace(/\s+\S*$/, "") + "..." : p.abstract);
      var tldr = el("p", p.tldr ? "tldr" : "tldr tldr-pending", text);
      tldr.lang = p.tldr ? "id" : "en";
      card.appendChild(tldr);
      results.appendChild(card);
    });
  }

  function run() {
    var text = input.value.trim().slice(0, 300);
    var topic = topicSelect.value;
    // Pilihan bahasa dari alamat halaman berlaku walaupun daftarnya belum dimuat.
    var lang = langSelect.value || langSelect.dataset.initial || "";
    var params = new URLSearchParams();
    if (text) params.set("q", text);
    if (topic) params.set("topik", topic);
    if (lang) params.set("bahasa", lang);
    var qs = params.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);

    if (!text) {
      results.innerHTML = "";
      setStatus("");
      return;
    }
    setStatus("Mencari...");
    loadIndex()
      .then(function () {
        var hasVectors = index.papers.some(function (p) { return p.vec; });
        if (!worker || !hasVectors) {
          return { items: keywordRank(text, topic, lang), semantic: false,
            note: "Pencarian semantik belum aktif, jadi hasil memakai kecocokan kata kunci." };
        }
        return embedQuery(text)
          .then(function (q) {
            return { items: semanticRank(q, topic, lang), semantic: true, note: "" };
          })
          .catch(function (err) {
            var reason = err.name === "AbortError" ? "waktu tunggu habis"
              : err instanceof TypeError ? "Worker tidak bisa dihubungi" : err.message;
            return { items: keywordRank(text, topic, lang), semantic: false,
              note: "Pencarian semantik sedang tidak bisa dipakai (" + reason + "), jadi hasil memakai kecocokan kata kunci." };
          });
      })
      .then(function (res) {
        if (input.value.trim().slice(0, 300) !== text) return;
        render(res.items, res.semantic);
        var summary = res.items.length
          ? (res.semantic
            ? res.items.length + " makalah yang maknanya paling dekat dengan pencarian Anda."
            : res.items.length + " makalah yang memuat kata pencarian Anda.")
          : "Tidak ada makalah yang cocok.";
        setStatus(res.note ? res.note + " " + summary : summary);
      })
      .catch(function (err) {
        setStatus("Indeks pencarian gagal dimuat (" + err.message + "). Coba muat ulang halaman.");
      });
  }

  var params = new URLSearchParams(location.search);
  input.value = params.get("q") || "";
  topicSelect.value = params.get("topik") || "";
  langSelect.dataset.initial = params.get("bahasa") || "";

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    run();
  });
  topicSelect.addEventListener("change", function () { if (input.value.trim()) run(); });
  langSelect.addEventListener("change", function () { if (input.value.trim()) run(); });

  loadIndex().catch(function () { /* pesan galat ditampilkan saat mencari */ });
  if (input.value.trim()) run(); else input.focus();
})();
