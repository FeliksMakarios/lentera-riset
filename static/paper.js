// Halaman makalah: pilihan bahasa ringkasan (Indonesia atau English) dan bagian
// ringkasan yang bisa dibuka dan ditutup. Kedua versi bahasa sudah ada di HTML;
// skrip ini hanya memilih mana yang tampil dan mengingat pilihan pembaca.
(function () {
  var L = window.Lentera;
  var article = document.querySelector("article.paper");
  if (!L || !article) return;

  var switches = article.querySelectorAll("[data-set-lang]");
  function setLang(lang) {
    if (lang !== "id" && lang !== "en") lang = "id";
    article.dataset.summaryLang = lang;
    Array.prototype.forEach.call(switches, function (b) {
      b.setAttribute("aria-pressed", b.dataset.setLang === lang ? "true" : "false");
    });
  }
  Array.prototype.forEach.call(switches, function (b) {
    b.addEventListener("click", function () {
      setLang(b.dataset.setLang);
      L.remember("bahasa-ringkasan", b.dataset.setLang);
    });
  });
  setLang(L.recall("bahasa-ringkasan") || "id");

  // Buka semua / tutup semua bagian ringkasan.
  var sections = article.querySelectorAll(".summary-section > details");
  var all = document.getElementById("sum-all");
  function refreshAll() {
    if (!all) return;
    var anyClosed = Array.prototype.some.call(sections, function (d) { return !d.open; });
    all.textContent = anyClosed ? "Buka semua bagian" : "Tutup semua bagian";
  }
  if (all && sections.length) {
    all.hidden = false;
    all.addEventListener("click", function () {
      var open = Array.prototype.some.call(sections, function (d) { return !d.open; });
      Array.prototype.forEach.call(sections, function (d) { d.open = open; });
      refreshAll();
    });
    Array.prototype.forEach.call(sections, function (d) {
      d.addEventListener("toggle", refreshAll);
    });
  }

  // Tautan langsung ke satu bagian (misalnya #method) membuka bagian itu.
  function openFromHash() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    var target = document.getElementById(id);
    var details = target && target.classList.contains("summary-section") && target.querySelector("details");
    if (details) {
      details.open = true;
      refreshAll();
      target.scrollIntoView({ block: "start" });
    }
  }
  window.addEventListener("hashchange", openFromHash);
  openFromHash();
  refreshAll();
})();
