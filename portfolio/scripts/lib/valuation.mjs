// Provisional valuation model. NOT a realized-sale average. Every input is an explicit assumption
// recorded in the asset's valuation.assumptions. Sample size of realized comparables is 0 for all
// pre-revenue code/IP assets (see research/market-sources.md).
import { roundTo } from "./util.mjs";

export const MODEL = Object.freeze({
  version: "1.0.0",
  loc_per_person_week: 200,        // tested production code incl. design/debug/review (assumption)
  test_loc_weight: 0.5,            // test code counts at half weight (assumption)
  rate_per_person_week_usd: 4000,  // blended contractor rate, ~$100/h x 40h (assumption)
  realization_band: [0.25, 0.60],  // fraction of replacement cost a buyer pays for a pre-revenue,
                                   // zero-traction, single-owner code asset (assumption; unvalidated)
  license_fraction: [0.15, 0.30],  // non-exclusive license as fraction of source-transfer price
  rounding_step: 500,
});

export function replacementCost({ srcLoc, testLoc }, m = MODEL) {
  const weeks = (srcLoc + m.test_loc_weight * testLoc) / m.loc_per_person_week;
  return { person_weeks: Math.round(weeks * 10) / 10, cost: weeks * m.rate_per_person_week_usd };
}

export function priceBands(loc, m = MODEL) {
  const rc = replacementCost(loc, m);
  const low = roundTo(rc.cost * m.realization_band[0], m.rounding_step);
  const high = roundTo(rc.cost * m.realization_band[1], m.rounding_step);
  const mid = roundTo((low + high) / 2, m.rounding_step);
  return {
    person_weeks: rc.person_weeks,
    replacement_cost: roundTo(rc.cost, m.rounding_step),
    source_transfer: { range: [low, high], price: mid },
    license: {
      range: [roundTo(low * m.license_fraction[0], m.rounding_step), roundTo(high * m.license_fraction[1], m.rounding_step)],
      price: roundTo(mid * ((m.license_fraction[0] + m.license_fraction[1]) / 2), m.rounding_step),
    },
  };
}
