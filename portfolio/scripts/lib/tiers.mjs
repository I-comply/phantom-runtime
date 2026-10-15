// Deny-by-default projection of a full asset record onto the PUBLIC tier.
// Anything not explicitly listed here can never reach a public page, deck or JSON payload.
export const PUBLIC_SCALARS = [
  "asset_id", "slug", "name", "brand", "creator_attribution", "disposition", "asset_type", "category",
  "one_line_value_proposition", "buyer_problem", "solution_summary_public", "maturity", "deployment_status",
  "test_status", "revenue_status", "traction_status", "contact_cta", "last_reviewed",
];
export const PUBLIC_ARRAYS = ["differentiators_public", "verified_capabilities", "unverified_claims"];
export const PACKAGE_PUBLIC = ["package_name", "package_type", "price_range", "rights_granted", "exclusions", "support_period", "transfer_deliverables", "availability"];

// Words that must never appear in public output (case-insensitive substrings).
export const FORBIDDEN_PUBLIC_MARKERS = ["BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE", "sk-emergent", "ghp_", "AKIA", "source_provenance", "ownership.contributors", "OWNER_PRIVATE", "UNALLOCATED_PENDING_CONTRIBUTION_AUDIT"];

export function toPublic(rec) {
  const out = {};
  for (const k of PUBLIC_SCALARS) if (rec[k] !== undefined) out[k] = rec[k];
  for (const k of PUBLIC_ARRAYS) out[k] = [...(rec[k] || [])];
  out.target_buyer = { segments: rec.target_buyer?.segments || [], buyer_roles: rec.target_buyer?.buyer_roles || [] };
  out.acquisition_packages = (rec.acquisition_packages || []).map((p) => Object.fromEntries(PACKAGE_PUBLIC.filter((k) => k in p).map((k) => [k, p[k]])));
  out.valuation_public = rec.public?.valuation_public || null;
  out.public = rec.public || {};
  out.publication = { approved: !!rec.publication?.approved };
  return out;
}
