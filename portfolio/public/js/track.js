/* Privacy-respecting first-party event counter: no cookies, no identifiers, allowlisted names only. */
(function () {
  window.PWXTrack = function (name, asset) {
    try { if (navigator.doNotTrack === "1") return; navigator.sendBeacon("/api/event", new Blob([JSON.stringify({ name: name, asset: asset || null })], { type: "application/json" })); } catch (e) {}
  };
  document.addEventListener("click", function (e) {
    const a = e.target.closest("[data-track]");
    if (a) window.PWXTrack(a.dataset.track, a.dataset.asset);
  });
})();
