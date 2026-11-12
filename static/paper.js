// Halaman makalah: bagian ringkasan yang bisa dibuka dan ditutup, label bahasa tambahan,
// kutipan (APA dan BibTeX), dan tombol salin tautan. Pilihan bahasa ringkasan (Indonesia
// atau English) diatur app.js untuk seluruh situs.
(function () {
  var L = window.Lentera;
  var article = document.querySelector("article.paper");
  if (!L || !article) return;

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

  // Tautan langsung ke satu bagian (misalnya #method atau #kutip) membuka bagian itu.
  function openFromHash() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    var target = document.getElementById(id);
    if (!target) return;
    var details = target.tagName === "DETAILS" ? target
      : target.classList.contains("summary-section") && target.querySelector("details");
    if (details) {
      details.open = true;
      refreshAll();
      target.scrollIntoView({ block: "start" });
    }
  }
  window.addEventListener("hashchange", openFromHash);
  openFromHash();
  refreshAll();

  // Label bahasa yang dilipat: "+N bahasa lainnya".
  var more = document.getElementById("chip-more");
  if (more) {
    more.hidden = false;
    more.addEventListener("click", function () {
      more.parentNode.classList.add("show-all");
      more.hidden = true;
    });
  }

  // Tombol "Kutip" membuka kotak kutipan meskipun alamatnya sudah berakhiran #kutip.
  var cite = document.getElementById("kutip");
  var citeJump = document.getElementById("cite-jump");
  if (cite && citeJump) {
    citeJump.addEventListener("click", function (e) {
      e.preventDefault();
      cite.open = true;
      cite.scrollIntoView({ behavior: "smooth", block: "start" });
      history.replaceState(null, "", "#kutip");
    });
  }

  // Salin kutipan dan salin tautan halaman.
  Array.prototype.forEach.call(document.querySelectorAll("[data-copy]"), function (button) {
    var source = document.getElementById(button.dataset.copy);
    if (!source) return;
    button.hidden = false;
    button.addEventListener("click", function () { L.copyText(source.textContent, button); });
  });
  var copyLink = document.getElementById("copy-link");
  if (copyLink) {
    copyLink.hidden = false;
    copyLink.addEventListener("click", function () {
      var canonical = document.querySelector('link[rel="canonical"]');
      L.copyText(canonical ? canonical.href : location.href.split("#")[0], copyLink);
    });
  }
})();
