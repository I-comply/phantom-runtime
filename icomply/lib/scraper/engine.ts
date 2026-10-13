import { prisma } from '../db';
import { notifyChange, notifySiteError } from '../notifications/notify';
import { diffSegments, extractText, hashText, isDue, summarizeDiff, MAX_STORED_TEXT } from './extract';
import { fetchHtml } from './fetch';
import { assertRobotsAllowed } from './robots';

export const MAX_CONSECUTIVE_FAILURES = 5;

export type ScrapeResult =
  | { ok: true; site: string; changed: boolean; baseline?: boolean }
  | { ok: false; site: string; error: string };

export async function runMunicipalScraper(siteId: string): Promise<ScrapeResult> {
  const site = await prisma.monitoredSite.findUnique({ where: { id: siteId } });
  if (!site) throw new Error(`Monitored site with ID ${siteId} not found.`);

  try {
    await assertRobotsAllowed(site.url);
    const html = await fetchHtml(site.url);
    const text = extractText(html, site.selector);
    if (!text) throw new Error(`Selector "${site.selector}" returned empty content`);

    const newHash = hashText(text);
    const now = new Date();
    const reset = { lastChecked: now, lastError: null, consecutiveFailures: 0 };

    if (site.lastHash === newHash) {
      await prisma.monitoredSite.update({ where: { id: site.id }, data: { ...reset, status: site.status === 'ERROR' ? 'ACTIVE' : site.status } });
      return { ok: true, site: site.name, changed: false };
    }

    const isBaseline = site.lastHash == null;
    const diffSummary = summarizeDiff(site.lastText, text);
    const diff = isBaseline || site.lastText == null ? null : diffSegments(site.lastText, text);
    const cap = (a: string[]) => (a.length ? a.join('\n').slice(0, 20_000) : null);

    // Optimistic guard: a concurrent run that already recorded this change makes count 0.
    const log = await prisma.$transaction(async (tx) => {
      const r = await tx.monitoredSite.updateMany({
        where: { id: site.id, lastHash: site.lastHash },
        data: { ...reset, lastHash: newHash, lastText: text.slice(0, MAX_STORED_TEXT), status: site.status === 'ERROR' ? 'ACTIVE' : site.status },
      });
      if (r.count === 0) return null;
      return tx.changeLog.create({
        data: { monitoredSiteId: site.id, oldHash: site.lastHash, newHash, diffSummary, isBaseline, detectedAt: now, addedText: diff && cap(diff.added), removedText: diff && cap(diff.removed) },
      });
    });

    if (!log) return { ok: true, site: site.name, changed: false };
    if (!isBaseline) {
      try {
        await notifyChange(log, site);
      } catch (e: any) {
        console.error(`[iComply] notify failed for ${site.name}: ${e.message}`);
      }
    }
    return { ok: true, site: site.name, changed: true, baseline: isBaseline };
  } catch (error: any) {
    const cause = error.response ? `HTTP ${error.response.status}` : error.message;
    const failures = site.consecutiveFailures + 1;
    const suspended = failures >= MAX_CONSECUTIVE_FAILURES && site.status === 'ACTIVE';
    await prisma.monitoredSite.update({
      where: { id: site.id },
      data: {
        lastChecked: new Date(),
        lastError: String(cause).slice(0, 500),
        consecutiveFailures: failures,
        status: suspended ? 'ERROR' : site.status,
      },
    });
    console.error(`[iComply] scrape failed for ${site.url}: ${cause}`);
    if (suspended) await notifySiteError(site, String(cause)).catch((e) => console.error(`[iComply] alert failed: ${e.message}`));
    return { ok: false, site: site.name, error: String(cause) };
  }
}

export async function runAllActive(concurrency = 3): Promise<ScrapeResult[]> {
  const all = await prisma.monitoredSite.findMany({
    where: { status: 'ACTIVE' },
    select: { id: true, lastChecked: true, intervalMinutes: true },
  });
  const sites = all.filter((s) => isDue(s));
  const results: ScrapeResult[] = [];
  let i = 0;
  const worker = async () => {
    while (i < sites.length) {
      const id = sites[i++].id;
      try {
        results.push(await runMunicipalScraper(id));
      } catch (e: any) {
        results.push({ ok: false, site: id, error: e.message });
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, sites.length) }, worker));
  return results;
}
