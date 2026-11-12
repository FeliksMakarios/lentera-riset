// Fungsi bersama (window.Lentera), pilihan bahasa ringkasan, menu di ponsel, dan tab di Beranda.
(function () {
  var body = document.body;
  var html = document.documentElement;
  var root = body.dataset.root || "";
  var MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember"];

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

  // Sama dengan slug() di lentera/build.py.
  function paperUrl(id) { return root + "papers/" + id.replace(/[\/:]/g, "_") + ".html"; }

  function dateLabel(iso) {
    var parts = (iso || "").split("-");
    if (parts.length < 3) return iso || "";
    return parseInt(parts[2], 10) + " " + MONTHS[parseInt(parts[1], 10) - 1] + " " + parts[0];
  }

  // ---------------------------------------------------------------------------
  // Bahasa ringkasan dan TL;DR (Indonesia atau English), berlaku di seluruh situs.
  // ---------------------------------------------------------------------------
  function currentLang() { return html.getAttribute("data-ringkasan") === "en" ? "en" : "id"; }
  function setLang(lang, store) {
    if (lang !== "id" && lang !== "en") lang = "id";
    html.setAttribute("data-ringkasan", lang);
    Array.prototype.forEach.call(document.querySelectorAll("[data-set-lang]"), function (b) {
      b.setAttribute("aria-pressed", b.dataset.setLang === lang ? "true" : "false");
    });
    if (store) remember("bahasa-ringkasan", lang);
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-set-lang]") : null;
    if (btn) setLang(btn.dataset.setLang, true);
  });
  setLang(currentLang(), false);

  // Kartu makalah; bentuknya sama dengan card() di lentera/build.py. `texts` berasal dari
  // texts.json: [TL;DR Indonesia, TL;DR Inggris] atau [cuplikan abstrak].
  function renderCard(p, catalog, opts, texts) {
    opts = opts || {};
    var card = el("article", "card");
    var meta = el("div", "card-meta");
    if (opts.rank) meta.appendChild(el("span", "rank", String(opts.rank)));
    if (p["new"]) meta.appendChild(el("span", "badge-new", "Baru"));
    var time = el("time", "", dateLabel(p.date));
    time.setAttribute("datetime", p.date);
    meta.appendChild(time);
    meta.appendChild(el("span", "source", p.source));
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
    link.href = paperUrl(p.id);
    h2.appendChild(link);
    card.appendChild(h2);
    card.appendChild(el("p", "authors", p.authors));
    var text = (texts && texts[p.id]) || [];
    if (text.length === 2) {
      var id = el("p", "tldr");
      id.lang = "id";
      id.dataset.l = "id";
      id.appendChild(withItalics(text[0]));
      card.appendChild(id);
      var en = el("p", "tldr tldr-en", text[1]);
      en.lang = "en";
      en.dataset.l = "en";
      card.appendChild(en);
    } else if (text.length === 1) {
      var pending = el("p", "tldr tldr-pending", text[0]);
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
    history.replaceState(null, "", (qs ? "?" + qs : location.pathname) + location.hash);
  }

  // Salin teks ke papan klip; label tombol berubah menjadi "Tersalin" sebentar.
  function copyText(text, button) {
    function done(ok) {
      if (!button) return;
      var label = button.lastChild;
      if (!button.dataset.label) button.dataset.label = label.textContent;
      label.textContent = ok ? "Tersalin" : "Gagal disalin";
      button.classList.toggle("copied", ok);
      setTimeout(function () {
        label.textContent = button.dataset.label;
        button.classList.remove("copied");
      }, 1800);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      return;
    }
    var area = el("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    body.removeChild(area);
    done(ok);
  }

  window.Lentera = {
    root: root, el: el, withItalics: withItalics, remember: remember, recall: recall,
    loadJSON: loadJSON, renderCard: renderCard, renderPager: renderPager, paperUrl: paperUrl,
    dateLabel: dateLabel, params: params, setParams: setParams, filterLink: filterLink,
    currentLang: currentLang, setLang: setLang, copyText: copyText
  };

  // ---------------------------------------------------------------------------
  // Kepala halaman di ponsel: tombol cari dan tombol menu.
  // ---------------------------------------------------------------------------
  var header = document.getElementById("site-header");
  var searchToggle = document.getElementById("search-toggle");
  var menuToggle = document.getElementById("menu-toggle");
  function toggle(cls, button, open) {
    header.classList.toggle(cls, open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (header && searchToggle && menuToggle) {
    searchToggle.addEventListener("click", function () {
      var open = !header.classList.contains("search-open");
      toggle("search-open", searchToggle, open);
      toggle("menu-open", menuToggle, false);
      if (open) document.getElementById("site-q").focus();
    });
    menuToggle.addEventListener("click", function () {
      var open = !header.classList.contains("menu-open");
      toggle("menu-open", menuToggle, open);
      menuToggle.setAttribute("aria-label", open ? "Tutup menu" : "Buka menu");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && header.classList.contains("menu-open")) {
        toggle("menu-open", menuToggle, false);
        menuToggle.focus();
      }
    });
  }

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
  var tabs = [tabTrending, tabNewest];

  function show(tab) {
    var newest = tab === "terbaru";
    tabTrending.setAttribute("aria-selected", newest ? "false" : "true");
    tabNewest.setAttribute("aria-selected", newest ? "true" : "false");
    tabTrending.tabIndex = newest ? -1 : 0;
    tabNewest.tabIndex = newest ? 0 : -1;
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
    Promise.all([loadJSON("catalog.json"), loadJSON("texts.json")]).then(function (loaded) {
      var catalog = loaded[0];
      var sorted = catalog.papers.slice().sort(function (a, b) {
        return b.date.localeCompare(a.date) || b.score - a.score;
      });
      list.innerHTML = "";
      sorted.slice((page - 1) * perPage, page * perPage).forEach(function (p) {
        list.appendChild(renderCard(p, catalog, {}, loaded[1]));
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
  // Panah kiri dan kanan berpindah tab, seperti pola tablist pada umumnya.
  tabs.forEach(function (tab, i) {
    tab.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      var next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      next.click();
    });
  });
  var newLink = document.getElementById("new-link");
  if (newLink) {
    newLink.addEventListener("click", function (e) {
      e.preventDefault();
      page = 1;
      initPager();
      show("terbaru");
      tabNewest.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  var initial = params();
  var startPage = parseInt(initial.get("hal"), 10) || 1;
  if (initial.get("tab") === "terbaru" || (!initial.get("tab") && recall("tab") === "terbaru")) {
    if (startPage > 1) goTo(startPage, false);
    else { initPager(); show("terbaru"); }
  } else {
    tabTrending.tabIndex = 0;
    tabNewest.tabIndex = -1;
  }
})();
