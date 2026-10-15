import * as cheerio from 'cheerio';
import crypto from 'crypto';

export const MAX_STORED_TEXT = 500_000;

export function extractText(html: string, selector: string): string {
  const $ = cheerio.load(html);
  $('script, style, noscript').remove();
  $('br').replaceWith(' ');
  $('p, div, li, tr, td, th, h1, h2, h3, h4, h5, h6, section, article, blockquote, dt, dd').append(' ');
  return $(selector).text().replace(/\s+/g, ' ').trim();
}

export function hashText(text: string): string {
  return crypto.createHash('sha256').update(text).digest('hex');
}

export function validateSelector(selector: string): void {
  const $ = cheerio.load('<html><body></body></html>');
  $(selector); // throws on invalid syntax
}

const segment = (t: string) => t.split(/(?<=[.;:!?])\s+/).filter(Boolean);

export function diffSegments(oldText: string, newText: string) {
  const o = new Set(segment(oldText));
  const n = new Set(segment(newText));
  return { added: [...n].filter((s) => !o.has(s)), removed: [...o].filter((s) => !n.has(s)) };
}

export function summarizeDiff(oldText: string | null, newText: string): string {
  if (oldText == null) return `Baseline captured. Length: ${newText.length} chars.`;
  const { added, removed } = diffSegments(oldText, newText);
  const sample = added.slice(0, 3).map((s) => (s.length > 200 ? `${s.slice(0, 197)}...` : s));
  let out = `Ordinance content updated: ${added.length} segment(s) added, ${removed.length} removed. Length ${oldText.length} -> ${newText.length} chars.`;
  if (sample.length) out += ` Added: ${sample.map((s) => `"${s}"`).join(' | ')}`;
  return out;
}

export function isDue(site: { lastChecked: Date | null; intervalMinutes: number }, now = new Date()): boolean {
  if (!site.lastChecked) return true;
  return now.getTime() - site.lastChecked.getTime() >= site.intervalMinutes * 60_000 - 60_000;
}
