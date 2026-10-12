import axios from 'axios';
import * as cheerio from 'cheerio';
import crypto from 'crypto';
import { prisma } from '../db';

export async function runMunicipalScraper(siteId: string) {
  const site = await prisma.monitoredSite.findUnique({ where: { id: siteId } });
  if (!site) throw new Error(`Monitored site with ID ${siteId} not found.`);

  try {
    const response = await axios.get<string>(site.url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Compatible; iComply-Sentinel/1.0; +https://icomply.local)',
      },
      timeout: 15000,
      maxContentLength: 10 * 1024 * 1024,
      responseType: 'text',
    });

    const $ = cheerio.load(response.data);
    const normalizedText = $(site.selector).text().replace(/\s+/g, ' ').trim();
    if (!normalizedText) {
      throw new Error(`Selector "${site.selector}" returned empty content`);
    }

    const newHash = crypto.createHash('sha256').update(normalizedText).digest('hex');
    const now = new Date();

    if (site.lastHash === newHash) {
      await prisma.monitoredSite.update({ where: { id: site.id }, data: { lastChecked: now } });
      return { updated: false as const, site: site.name };
    }

    const diffSummary = `Ordinance content updated. Length: ${normalizedText.length} chars.`;
    await prisma.$transaction([
      prisma.changeLog.create({
        data: { monitoredSiteId: site.id, oldHash: site.lastHash, newHash, diffSummary },
      }),
      prisma.monitoredSite.update({
        where: { id: site.id },
        data: { lastHash: newHash, lastChecked: now },
      }),
    ]);

    return { updated: true as const, site: site.name, newHash, diffSummary, detectedAt: now.toISOString() };
  } catch (error: any) {
    const cause = error.response ? `HTTP Status ${error.response.status}` : error.message;
    throw new Error(`Scraper execution failed for ${site.url}. Cause: ${cause}`);
  }
}
