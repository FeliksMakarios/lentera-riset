// Fungsi bersama (window.Lentera) dan tab di Beranda.
(function () {
  var body = document.body;
  var root = body.dataset.root || "";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  // Ubah *istilah* menjadi <em>istilah</em> tanpa menyisipkan HTML mentah.
  function withItalics(text) {
    var frag = document.createDocumentFragment();
    var re = /\*([^*\n]+?)\*/g;
    var last = 0;
    var m;
    while ((m = re.exec(text))) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(el("em", "", m[1]));
      last = re.lastIndex;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    return frag;
  }

  function remember(key, value) {
    try { localStorage.setItem("lentera:" + key, value); } catch (e) { /* abaikan */ }
  }
  function recall(key) {
    try { return localStorage.getItem("lentera:" + key); } catch (e) { return null; }
  }

  var cache = {};
  function loadJSON(name) {
    if (!cache[name]) {
      cache[name] = fetch(root + name).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    }
    return cache[name];
  }

  function filterLink(key, value) {
    return root + "makalah.html?" + key + "=" + encodeURIComponent(value);
  }

  // Kartu makalah; bentuknya sama dengan card() di lentera/build.py.
  function renderCard(p, catalog, opts) {
    opts = opts || {};
    var card = el("article", "card");
    var meta = el("div", "card-meta");
    if (opts.rank) meta.appendChild(el("span", "rank", String(opts.rank)));
    var time = el("time", "", p.date_label);
    time.setAttribute("datetime", p.date);
    meta.appendChild(time);
    meta.appendChild(el("span", "", p.source));
    p.topics.forEach(function (t) {
      if (!catalog.topics[t]) return;
      var chip = el("a", "chip chip-" + t, catalog.topics[t]);
      chip.href = filterLink("topik", t);
      meta.appendChild(chip);
    });
    if (opts.similarity != null) {
      meta.appendChild(el("span", "match", "kemiripan " + Math.round(opts.similarity * 100) + "%"));
    }
    card.appendChild(meta);
    var h2 = el("h2");
    var link = el("a", "", p.title);
    link.href = root + p.url;
    h2.appendChild(link);
    card.appendChild(h2);
    card.appendChild(el("p", "authors", p.authors));
    if (p.tldr) {
      var id = el("p", "tldr");
      id.lang = "id";
      id.appendChild(withItalics(p.tldr));
      card.appendChild(id);
      var en = el("p", "tldr tldr-en", p.tldr_en);
      en.lang = "en";
      card.appendChild(en);
    } else {
      var pending = el("p", "tldr tldr-pending", p.snippet);
      pending.lang = "en";
      card.appendChild(pending);
    }
    return card;
  }

  // Navigasi halaman: < Sebelumnya 1 ... 4 5 6 ... 20 Berikutnya >
  function renderPager(nav, page, pages, onGo) {
    nav.innerHTML = "";
    if (pages <= 1) return;
    function button(label, target, current, disabled) {
      var b = el("button", "pager-btn", label);
      b.type = "button";
      if (current) { b.setAttribute("aria-current", "page"); b.classList.add("current"); }
      if (disabled) b.disabled = true;
      else b.addEventListener("click", function () { onGo(target); });
      nav.appendChild(b);
    }
    button("‹ Sebelumnya", page - 1, false, page <= 1);
    var shown = {};
    [1, pages, page - 1, page, page + 1].forEach(function (n) {
      if (n >= 1 && n <= pages) shown[n] = true;
    });
    var prev = 0;
    Object.keys(shown).map(Number).sort(function (a, b) { return a - b; }).forEach(function (n) {
      if (n - prev > 1) nav.appendChild(el("span", "pager-gap", "…"));
      button(String(n), n, n === page, false);
      prev = n;
    });
    button("Berikutnya ›", page + 1, false, page >= pages);
  }

  function params() { return new URLSearchParams(location.search); }
  function setParams(p) {
    var qs = p.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  window.Lentera = {
    root: root, el: el, withItalics: withItalics, remember: remember, recall: recall,
    loadJSON: loadJSON, renderCard: renderCard, renderPager: renderPager,
    params: params, setParams: setParams, filterLink: filterLink
  };

  // ---------------------------------------------------------------------------
  // Beranda: tab "Sedang ramai" dan "Terbaru" (beberapa makalah per halaman).
  // ---------------------------------------------------------------------------
  var tabTrending = document.getElementById("tab-trending");
  var tabNewest = document.getElementById("tab-newest");
  if (!tabTrending || !tabNewest) return;
  var panelTrending = document.getElementById("panel-trending");
  var panelNewest = document.getElementById("panel-newest");
  var list = document.getElementById("newest-list");
  var pager = document.getElementById("newest-pager");
  var perPage = parseInt(panelNewest.dataset.perPage, 10) || 7;
  var pages = parseInt(pager.dataset.pages, 10) || 1;
  var page = 1;

  function show(tab) {
    var newest = tab === "terbaru";
    tabTrending.setAttribute("aria-selected", newest ? "false" : "true");
    tabNewest.setAttribute("aria-selected", newest ? "true" : "false");
    panelTrending.hidden = newest;
    panelNewest.hidden = !newest;
    remember("tab", tab);
    var p = params();
    if (newest) p.set("tab", "terbaru"); else p.delete("tab");
    if (newest && page > 1) p.set("hal", page); else p.delete("hal");
    setParams(p);
  }

  function goTo(n, scroll) {
    page = Math.min(Math.max(1, n), pages);
    renderPager(pager, page, pages, function (target) { goTo(target, true); });
    show("terbaru");
    loadJSON("catalog.json").then(function (catalog) {
      var sorted = catalog.papers.slice().sort(function (a, b) {
        return b.date.localeCompare(a.date) || b.score - a.score;
      });
      list.innerHTML = "";
      sorted.slice((page - 1) * perPage, page * perPage).forEach(function (p) {
        list.appendChild(renderCard(p, catalog));
      });
      if (scroll) tabNewest.scrollIntoView({ behavior: "smooth", block: "start" });
    }).catch(function () {
      list.innerHTML = "";
      list.appendChild(el("p", "empty", "Daftar makalah gagal dimuat. Coba muat ulang halaman."));
    });
  }

  function initPager() {
    renderPager(pager, page, pages, function (target) { goTo(target, true); });
  }

  tabTrending.addEventListener("click", function () { show("ramai"); });
  tabNewest.addEventListener("click", function () { initPager(); show("terbaru"); });

  var initial = params();
  var startPage = parseInt(initial.get("hal"), 10) || 1;
  if (initial.get("tab") === "terbaru" || (!initial.get("tab") && recall("tab") === "terbaru")) {
    if (startPage > 1) goTo(startPage, false);
    else { initPager(); show("terbaru"); }
  }
})();
