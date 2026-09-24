// Pengurutan, penyaringan topik, dan pencarian di halaman depan.
(function () {
  var list = document.getElementById("paper-list");
  if (!list) return;

  var cards = Array.prototype.slice.call(list.querySelectorAll(".card"));
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  var topicSelect = document.getElementById("topic-filter");
  var search = document.getElementById("search");
  var count = document.getElementById("result-count");
  var noResults = document.getElementById("no-results");

  function remember(key, value) {
    try { localStorage.setItem("lentera:" + key, value); } catch (e) { /* abaikan */ }
  }
  function recall(key) {
    try { return localStorage.getItem("lentera:" + key); } catch (e) { return null; }
  }

  var sortBy = recall("sort") === "date" ? "date" : "score";

  function apply() {
    var topic = topicSelect.value;
    var terms = search.value.toLowerCase().split(/\s+/).filter(Boolean);

    cards.sort(function (a, b) {
      if (sortBy === "date") return b.dataset.date.localeCompare(a.dataset.date);
      return parseFloat(b.dataset.score) - parseFloat(a.dataset.score);
    });

    var shown = 0;
    cards.forEach(function (card) {
      var topics = card.dataset.topics.split(" ");
      var text = card.dataset.search;
      var ok = (!topic || topics.indexOf(topic) !== -1) &&
        terms.every(function (t) { return text.indexOf(t) !== -1; });
      card.hidden = !ok;
      if (ok) shown++;
      list.appendChild(card);
    });

    tabs.forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.dataset.sort === sortBy ? "true" : "false");
    });
    count.textContent = shown + " makalah";
    noResults.hidden = shown !== 0 || cards.length === 0;
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      sortBy = tab.dataset.sort;
      remember("sort", sortBy);
      apply();
    });
  });
  topicSelect.addEventListener("change", apply);
  search.addEventListener("input", apply);
  apply();
})();
