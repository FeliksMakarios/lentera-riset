// Tanya jawab di halaman makalah. Pertanyaan dikirim ke POST /ask di Worker, yang
// membaca PDF makalah (atau abstrak dan ringkasan jika PDF tidak tersedia) dan
// meminta Gemini menjawab. Percakapan disimpan selama sesi peramban, jadi tidak
// hilang saat halaman dimuat ulang.
//
// Di layar lebar, panel menempel di sisi kanan dan lebarnya bisa diatur. Di layar
// kecil, panel muncul dari bawah lewat tombol mengambang. Pembaca bisa memilih teks
// di halaman untuk dikutip, atau menanyakan satu bagian ringkasan lewat ikon di
// judul bagian itu.
(function () {
  var L = window.Lentera;
  var panel = document.getElementById("tanya");
  var layout = document.getElementById("paper-layout");
  var worker = (document.body.dataset.worker || "").replace(/\/+$/, "");
  if (!L || !panel || !layout || !worker) return;

  var paper = panel.dataset.paper;
  var article = layout.querySelector("article.paper");
  var log = document.getElementById("ask-log");
  var scroller = document.getElementById("ask-scroll");
  var form = document.getElementById("ask-form");
  var input = document.getElementById("ask-q");
  var send = document.getElementById("ask-send");
  var clear = document.getElementById("ask-clear");
  var suggest = document.getElementById("ask-suggest");
  var closeBtn = document.getElementById("ask-close");
  var openBtn = document.getElementById("ask-open");
  var jump = document.getElementById("ask-jump");
  var resize = document.getElementById("ask-resize");
  var quoteBox = document.getElementById("ask-quote");
  var quoteText = document.getElementById("ask-quote-text");
  var quoteRemove = document.getElementById("ask-quote-remove");
  var quotePop = document.getElementById("quote-pop");

  var KEY = "lentera:ask:" + paper;
  var HISTORY_SENT = 6;
  var MAX_QUOTE = 600;
  var MIN_WIDTH = 320;
  var DEFAULT_WIDTH = 420;
  var wide = window.matchMedia("(min-width: 1100px)");
  var busy = false;
  var quote = "";

  // ---------------------------------------------------------------------------
  // Percakapan
  // ---------------------------------------------------------------------------
  function load() {
    try {
      var saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
      if (saved && Array.isArray(saved.turns)) return saved;
    } catch (e) { /* abaikan */ }
    return { turns: [], file: null };
  }
  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* abaikan */ }
  }
  var state = load();

  // **tebal** dan *miring*, tanpa menyisipkan HTML mentah.
  function inline(text) {
    var frag = document.createDocumentFragment();
    var re = /\*\*([^*\n]+?)\*\*|\*([^*\n]+?)\*/g;
    var last = 0;
    var m;
    while ((m = re.exec(text))) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(m[1] ? L.el("strong", "", m[1]) : L.el("em", "", m[2]));
      last = re.lastIndex;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    return frag;
  }

  // Paragraf dipisah baris kosong; baris berawalan "- ", "* ", atau "1. " menjadi daftar.
  function formatAnswer(text) {
    var frag = document.createDocumentFragment();
    text.split(/\n\s*\n/).forEach(function (block) {
      var list = null;
      var para = null;
      block.split("\n").forEach(function (raw) {
        var line = raw.trim();
        if (!line) return;
        var bullet = /^[-*•]\s+(.*)$/.exec(line);
        var number = /^\d+[.)]\s+(.*)$/.exec(line);
        if (bullet || number) {
          var tag = bullet ? "ul" : "ol";
          if (!list || list.tagName.toLowerCase() !== tag) {
            list = L.el(tag);
            frag.appendChild(list);
          }
          var li = L.el("li");
          li.appendChild(inline((bullet || number)[1]));
          list.appendChild(li);
          para = null;
          return;
        }
        list = null;
        if (!para) {
          para = L.el("p");
          frag.appendChild(para);
        } else {
          para.appendChild(document.createElement("br"));
        }
        para.appendChild(inline(line));
      });
    });
    return frag;
  }

  function bubble(turn) {
    var item = L.el("div", "ask-turn ask-" + turn.role);
    item.appendChild(L.el("span", "ask-who", turn.role === "user" ? "Anda" : "Lentera"));
    var body = L.el("div", "ask-text");
    if (turn.role === "user") {
      if (turn.quote) body.appendChild(L.el("blockquote", "ask-quoted", turn.quote));
      body.appendChild(document.createTextNode(turn.quote ? turn.ask || "" : turn.text));
    } else {
      body.appendChild(formatAnswer(turn.text));
    }
    item.appendChild(body);
    if (turn.role === "model" && turn.source === "abstract") {
      item.appendChild(L.el("p", "ask-meta", "Dijawab dari abstrak dan ringkasan, karena PDF makalah tidak bisa dibaca."));
    }
    return item;
  }

  function toBottom() { scroller.scrollTop = scroller.scrollHeight; }

  function render() {
    log.innerHTML = "";
    state.turns.forEach(function (turn) { log.appendChild(bubble(turn)); });
    clear.hidden = !state.turns.length;
    suggest.hidden = state.turns.length > 0;
    toBottom();
  }

  function errorText(status, message) {
    if (status === 429) return "Terlalu banyak pertanyaan dalam waktu singkat. Tunggu sekitar satu menit, lalu coba lagi.";
    if (status === 503) return "Kuota Gemini sedang habis atau layanannya sibuk. Coba lagi beberapa saat lagi.";
    if (status === 404) return "Makalah ini belum dikenali layanan tanya jawab. Coba lagi setelah situs diperbarui.";
    return "Pertanyaan gagal dijawab (" + message + "). Coba lagi.";
  }

  function setBusy(on) {
    busy = on;
    send.disabled = on;
    input.disabled = on;
    panel.classList.toggle("ask-busy", on);
    send.setAttribute("aria-label", on ? "Menjawab..." : "Kirim pertanyaan");
  }

  function setQuote(text) {
    quote = (text || "").replace(/\s+/g, " ").trim().slice(0, MAX_QUOTE);
    quoteText.textContent = quote;
    quoteBox.hidden = !quote;
  }

  var QUOTE_ONLY = "Jelaskan kutipan ini.";

  function ask(question) {
    question = (question || "").trim().slice(0, 500);
    if (busy) return;
    var quoted = quote;
    if (quoted && question.length < 2) question = QUOTE_ONLY;
    if (question.length < 2) return;
    var full = quoted ? 'Kutipan dari halaman makalah: "' + quoted + '"\n\nPertanyaan: ' + question : question;
    var history = state.turns.slice(-HISTORY_SENT).map(function (t) { return { role: t.role, text: t.text }; });
    var userTurn = quoted ? { role: "user", text: full, quote: quoted, ask: question } : { role: "user", text: question };
    log.appendChild(bubble(userTurn));
    var pending = L.el("div", "ask-turn ask-model ask-pending");
    pending.appendChild(L.el("span", "ask-who", "Lentera"));
    pending.appendChild(L.el("div", "ask-text",
      state.file || state.turns.length ? "Sedang menjawab..." : "Sedang membaca makalah. Pertanyaan pertama bisa memakan waktu hingga setengah menit..."));
    log.appendChild(pending);
    suggest.hidden = true;
    input.value = "";
    setQuote("");
    setBusy(true);
    toBottom();

    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 90000) : null;
    fetch(worker + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper: paper, question: full, history: history, file: state.file }),
      signal: controller ? controller.signal : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var err = new Error(data.error || "HTTP " + r.status);
          err.status = r.status;
          throw err;
        }
        return data;
      });
    }).then(function (data) {
      state.file = data.file || null;
      state.turns.push(userTurn);
      state.turns.push({ role: "model", text: data.answer, source: data.source });
      save();
      render();
    }).catch(function (err) {
      pending.classList.remove("ask-pending");
      pending.classList.add("ask-error");
      var reason = err.name === "AbortError" ? "waktu tunggu habis"
        : err instanceof TypeError ? "layanan tidak bisa dihubungi" : err.message;
      pending.querySelector(".ask-text").textContent = errorText(err.status, reason);
      input.value = question === QUOTE_ONLY ? "" : question;
      setQuote(quoted);
      clear.hidden = false;
      toBottom();
    }).then(function () {
      if (timer) clearTimeout(timer);
      setBusy(false);
      input.focus();
    });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    ask(input.value);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      ask(input.value);
    }
  });
  Array.prototype.forEach.call(suggest.querySelectorAll(".ask-card"), function (card) {
    card.addEventListener("click", function () {
      ask(card.querySelector(".ask-card-text").textContent);
    });
  });
  clear.addEventListener("click", function () {
    state = { turns: [], file: state.file };
    save();
    render();
    input.focus();
  });
  quoteRemove.addEventListener("click", function () {
    setQuote("");
    input.focus();
  });

  // ---------------------------------------------------------------------------
  // Buka dan tutup panel
  // ---------------------------------------------------------------------------
  function isOpen() { return layout.dataset.ask === "open"; }

  function setOpen(open, byUser) {
    layout.dataset.ask = open ? "open" : "closed";
    openBtn.setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("ask-sheet-open", open && !wide.matches);
    document.body.classList.toggle("ask-docked", open && wide.matches);
    if (byUser && wide.matches) L.remember("panel-tanya", open ? "buka" : "tutup");
    place();
  }

  function openAndFocus() {
    setOpen(true, true);
    input.focus();
  }

  function initialState() {
    setOpen(wide.matches && L.recall("panel-tanya") !== "tutup", false);
  }

  closeBtn.addEventListener("click", function () {
    setOpen(false, true);
    openBtn.focus();
  });
  openBtn.addEventListener("click", openAndFocus);
  if (jump) {
    jump.addEventListener("click", function (e) {
      e.preventDefault();
      openAndFocus();
    });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isOpen() && !wide.matches) {
      setOpen(false, false);
      openBtn.focus();
    }
  });
  if (wide.addEventListener) wide.addEventListener("change", initialState);
  else if (wide.addListener) wide.addListener(initialState);

  // Di layar lebar panel dipasang tetap di layar, sejajar kolom kanan tata letak. Tepi
  // atasnya tidak naik melewati awal tata letak, supaya kepala halaman tidak tertutup.
  var askWidth = DEFAULT_WIDTH;
  var placeQueued = false;
  function place() {
    placeQueued = false;
    if (!wide.matches || !isOpen()) return;
    var r = layout.getBoundingClientRect();
    layout.style.setProperty("--ask-top", Math.max(12, Math.round(r.top + 12)) + "px");
    layout.style.setProperty("--ask-left", Math.round(r.right - askWidth) + "px");
  }
  function queuePlace() {
    if (placeQueued) return;
    placeQueued = true;
    requestAnimationFrame(place);
  }
  window.addEventListener("scroll", queuePlace, { passive: true });
  window.addEventListener("resize", function () {
    setWidth(askWidth, false);
    queuePlace();
  });

  // ---------------------------------------------------------------------------
  // Lebar panel: tarik pegangan di tepi kiri panel, atau pakai tombol panah.
  // ---------------------------------------------------------------------------
  function maxWidth() {
    return Math.max(MIN_WIDTH, Math.min(760, Math.round(layout.getBoundingClientRect().width * 0.55)));
  }
  function setWidth(px, store) {
    var w = Math.round(Math.min(Math.max(px, MIN_WIDTH), maxWidth()));
    askWidth = w;
    document.documentElement.style.setProperty("--ask-w", w + "px");
    resize.setAttribute("aria-valuenow", String(w));
    if (store) L.remember("lebar-panel-tanya", String(w));
    place();
  }
  function currentWidth() { return askWidth; }

  resize.setAttribute("aria-valuemin", String(MIN_WIDTH));
  resize.setAttribute("aria-valuemax", "760");
  resize.setAttribute("aria-valuenow", String(DEFAULT_WIDTH));
  setWidth(parseInt(L.recall("lebar-panel-tanya"), 10) || DEFAULT_WIDTH, false);

  resize.addEventListener("pointerdown", function (e) {
    if (!wide.matches) return;
    e.preventDefault();
    resize.setPointerCapture(e.pointerId);
    document.body.classList.add("ask-resizing");
    var right = layout.getBoundingClientRect().right;
    function move(ev) { setWidth(right - ev.clientX, false); }
    function up() {
      resize.removeEventListener("pointermove", move);
      resize.removeEventListener("pointerup", up);
      resize.removeEventListener("pointercancel", up);
      document.body.classList.remove("ask-resizing");
      setWidth(currentWidth(), true);
    }
    resize.addEventListener("pointermove", move);
    resize.addEventListener("pointerup", up);
    resize.addEventListener("pointercancel", up);
  });
  resize.addEventListener("dblclick", function () {
    L.remember("lebar-panel-tanya", "");
    setWidth(DEFAULT_WIDTH, false);
  });
  resize.addEventListener("keydown", function (e) {
    var step = e.shiftKey ? 80 : 24;
    if (e.key === "ArrowLeft") setWidth(currentWidth() + step, true);
    else if (e.key === "ArrowRight") setWidth(currentWidth() - step, true);
    else return;
    e.preventDefault();
  });

  // ---------------------------------------------------------------------------
  // Kutip teks pilihan dan tanyakan satu bagian ringkasan.
  // ---------------------------------------------------------------------------
  function selectedText() {
    var sel = window.getSelection ? window.getSelection() : null;
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    var range = sel.getRangeAt(0);
    var node = range.commonAncestorContainer;
    if (node.nodeType !== 1) node = node.parentNode;
    if (!article.contains(node)) return null;
    var text = sel.toString().replace(/\s+/g, " ").trim();
    if (text.length < 3) return null;
    return { text: text, rect: range.getBoundingClientRect() };
  }

  function placeQuotePop() {
    var picked = selectedText();
    if (!picked || busy) {
      quotePop.hidden = true;
      return;
    }
    quotePop.hidden = false;
    var top = picked.rect.top + window.scrollY - quotePop.offsetHeight - 8;
    if (picked.rect.top < quotePop.offsetHeight + 12) top = picked.rect.bottom + window.scrollY + 8;
    var left = picked.rect.left + window.scrollX + picked.rect.width / 2 - quotePop.offsetWidth / 2;
    var maxLeft = window.scrollX + document.documentElement.clientWidth - quotePop.offsetWidth - 8;
    quotePop.style.top = Math.round(top) + "px";
    quotePop.style.left = Math.round(Math.max(window.scrollX + 8, Math.min(left, maxLeft))) + "px";
  }

  var popTimer = null;
  document.addEventListener("selectionchange", function () {
    clearTimeout(popTimer);
    popTimer = setTimeout(placeQuotePop, 150);
  });
  // Mencegah pilihan teks hilang sebelum tombol diklik.
  quotePop.addEventListener("mousedown", function (e) { e.preventDefault(); });
  quotePop.addEventListener("click", function () {
    var picked = selectedText();
    if (!picked) return;
    setQuote(picked.text);
    quotePop.hidden = true;
    if (window.getSelection) window.getSelection().removeAllRanges();
    openAndFocus();
  });

  article.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".ask-section") : null;
    if (!btn) return;
    var en = article.dataset.summaryLang === "en";
    input.value = en
      ? 'Explain the "' + btn.dataset.sectionEn + '" section of this paper in more detail.'
      : 'Jelaskan lebih rinci bagian "' + btn.dataset.sectionId + '" dari makalah ini.';
    openAndFocus();
    input.setSelectionRange(input.value.length, input.value.length);
  });

  if (location.hash === "#tanya") setOpen(true, false);
  else initialState();
  layout.classList.add("ask-ready");
  render();
})();
