#!/usr/bin/env node
// Prints stored inquiries. Usage: node scripts/list-inquiries.mjs [file]   (default data/inquiries/inquiries.jsonl)
import fs from "node:fs";
import path from "node:path";
import { ROOT } from "./lib/util.mjs";

const file = process.argv[2] || process.env.PWX_INQUIRY_FILE || path.join(ROOT, "data/inquiries/inquiries.jsonl");
if (!fs.existsSync(file)) { console.log("No inquiries file at " + file); process.exit(0); }
for (const line of fs.readFileSync(file, "utf8").split("\n").filter(Boolean)) {
  try {
    const r = JSON.parse(line);
    console.log(`${r.reference}  ${r.received_at}  asset=${r.asset || "-"}  interest=${r.interest}\n  ${r.name} <${r.email}>${r.org ? " · " + r.org : ""}\n  ${r.message.replace(/\n/g, "\n  ")}\n`);
  } catch { console.error("skipped unreadable line"); }
}
