document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("inquiry-form"); if (!form) return;
  const out = document.getElementById("inquiry-result"), btn = form.querySelector("button[type=submit]");
  const p = new URLSearchParams(location.search); if (p.get("asset") && form.asset) { for (const o of form.asset.options) if (o.value === p.get("asset")) o.selected = true; }
  form.addEventListener("submit", async function (e) {
    e.preventDefault(); btn.disabled = true; out.hidden = false; out.className = "notice"; out.textContent = "Sending…";
    const body = Object.fromEntries(new FormData(form).entries()); body.consent = form.consent.checked;
    try {
      const r = await fetch("/api/inquiry", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (r.ok) { out.className = "notice good"; out.textContent = "Received. Reference " + j.reference + ". You will be contacted at the address you provided."; form.reset(); if (window.PWXTrack) window.PWXTrack("inquiry_submit", body.asset); }
      else { out.className = "notice bad"; out.textContent = (j.error || "Could not submit.") + (j.fields ? " Check: " + j.fields.join(", ") + "." : ""); }
    } catch (err) { out.className = "notice bad"; out.textContent = "Network error. Please use the email address shown on this page."; }
    btn.disabled = false;
  });
});
