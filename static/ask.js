// Tanya jawab di halaman makalah. Pertanyaan dikirim ke POST /ask di Worker, yang
// membaca PDF makalah (atau abstrak dan ringkasan jika PDF tidak tersedia) dan
// meminta Gemini menjawab. Percakapan disimpan selama sesi peramban, jadi tidak
// hilang saat halaman dimuat ulang.
(function () {
  var L = window.Lentera;
  var box = document.getElementById("tanya");
  var worker = (document.body.dataset.worker || "").replace(/\/+$/, "");
  if (!L || !box || !worker) return;

  var paper = box.dataset.paper;
  var log = document.getElementById("ask-log");
  var form = document.getElementById("ask-form");
  var input = document.getElementById("ask-q");
  var send = document.getElementById("ask-send");
  var clear = document.getElementById("ask-clear");
  var suggest = document.getElementById("ask-suggest");
  var KEY = "lentera:ask:" + paper;
  var HISTORY_SENT = 6;
  var busy = false;

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
    if (turn.role === "user") body.textContent = turn.text;
    else body.appendChild(formatAnswer(turn.text));
    item.appendChild(body);
    if (turn.role === "model" && turn.source === "abstract") {
      item.appendChild(L.el("p", "ask-meta", "Dijawab dari abstrak dan ringkasan, karena PDF makalah tidak bisa dibaca."));
    }
    return item;
  }

  function render() {
    log.innerHTML = "";
    state.turns.forEach(function (turn) { log.appendChild(bubble(turn)); });
    clear.hidden = !state.turns.length;
    suggest.hidden = state.turns.length > 0;
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
    send.textContent = on ? "Menjawab..." : "Tanya";
  }

  function ask(question) {
    question = question.trim().slice(0, 500);
    if (question.length < 2 || busy) return;
    var history = state.turns.slice(-HISTORY_SENT).map(function (t) { return { role: t.role, text: t.text }; });
    var userTurn = { role: "user", text: question };
    log.appendChild(bubble(userTurn));
    var pending = L.el("div", "ask-turn ask-model ask-pending");
    pending.appendChild(L.el("span", "ask-who", "Lentera"));
    pending.appendChild(L.el("div", "ask-text",
      state.file || state.turns.length ? "Sedang menjawab..." : "Sedang membaca makalah. Pertanyaan pertama bisa memakan waktu hingga setengah menit..."));
    log.appendChild(pending);
    suggest.hidden = true;
    input.value = "";
    setBusy(true);

    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 90000) : null;
    fetch(worker + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper: paper, question: question, history: history, file: state.file }),
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
      input.value = question;
      clear.hidden = false;
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
  Array.prototype.forEach.call(suggest.querySelectorAll(".ask-chip"), function (chip) {
    chip.addEventListener("click", function () { ask(chip.textContent); });
  });
  clear.addEventListener("click", function () {
    state = { turns: [], file: state.file };
    save();
    render();
    input.focus();
  });

  render();
})();
