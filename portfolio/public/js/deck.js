(function () {
  const slides = Array.from(document.querySelectorAll(".slide")); if (!slides.length) return;
  let i = 0; const label = document.getElementById("pos");
  function show(n) { i = Math.max(0, Math.min(slides.length - 1, n)); slides.forEach((s, k) => { s.hidden = k !== i; }); label.textContent = (i + 1) + " / " + slides.length; if (location.hash !== "#" + (i + 1)) history.replaceState(null, "", "#" + (i + 1)); }
  document.getElementById("prev").onclick = () => show(i - 1); document.getElementById("next").onclick = () => show(i + 1);
  document.addEventListener("keydown", (e) => { if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") { e.preventDefault(); show(i + 1); } if (e.key === "ArrowLeft" || e.key === "PageUp") show(i - 1); if (e.key === "n") document.body.classList.toggle("notes"); });
  show((parseInt(location.hash.slice(1), 10) || 1) - 1);
  window.addEventListener("beforeprint", () => slides.forEach((s) => (s.hidden = false)));
  window.addEventListener("afterprint", () => show(i));
})();
