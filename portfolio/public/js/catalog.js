/* Catalog search + filter. Progressive enhancement: without JS the full list is shown. */
(function (root) {
  function matches(a, f) {
    const q = (f.q || "").trim().toLowerCase();
    if (q) {
      const hay = [a.name, a.category, a.one_line_value_proposition, (a.target_buyer && a.target_buyer.segments || []).join(" ")].join(" ").toLowerCase();
      if (!q.split(/\s+/).every((t) => hay.includes(t))) return false;
    }
    if (f.category && a.category !== f.category) return false;
    if (f.maturity && a.maturity !== f.maturity) return false;
    if (f.type && a.asset_type !== f.type) return false;
    return true;
  }
  function filter(list, f) { return list.filter((a) => matches(a, f)); }
  root.PWXCatalog = { matches, filter };
  if (typeof module !== "undefined") module.exports = root.PWXCatalog;
  if (typeof document === "undefined") return;
  document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("catalog-filters");
    if (!form) return;
    form.hidden = false;
    fetch("/assets.json").then((r) => r.json()).then((data) => {
      const list = data.assets, cards = Array.from(document.querySelectorAll("[data-asset-id]")), status = document.getElementById("catalog-status");
      function apply() {
        const f = { q: form.q.value, category: form.category.value, maturity: form.maturity.value, type: form.type.value };
        const ids = new Set(filter(list, f).map((a) => a.asset_id));
        let n = 0;
        cards.forEach((c) => { const show = ids.has(c.dataset.assetId); c.hidden = !show; if (show) n++; });
        status.textContent = n + " of " + cards.length + " assets shown";
        if (window.PWXTrack) window.PWXTrack("catalog_filter");
      }
      const preset = new URLSearchParams(location.search).get("category"); if (preset) form.category.value = preset;
      form.addEventListener("input", apply);
      form.addEventListener("submit", (e) => e.preventDefault());
      apply();
    }).catch(function () { form.hidden = true; });
  });
})(typeof window !== "undefined" ? window : globalThis);
