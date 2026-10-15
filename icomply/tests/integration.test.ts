import http from 'http';
import { AddressInfo } from 'net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

process.env.ICOMPLY_ALLOW_PRIVATE_TARGETS = 'true';
process.env.ICOMPLY_ENCRYPTION_KEY = 'k'.repeat(40);

const run = process.env.DATABASE_URL ? describe : describe.skip;

run('scrape → diff → signed webhook (needs DATABASE_URL)', () => {
  let page = '<div id="o"><p>Sec 1. Parking limit 2h.</p></div>';
  const robots = 'User-agent: *\nDisallow: /secret';
  const received: { headers: http.IncomingHttpHeaders; body: string }[] = [];
  let site: http.Server, hook: http.Server, base: string, hookUrl: string;

  beforeAll(async () => {
    site = http.createServer((req, res) => {
      if (req.url === '/robots.txt') { res.writeHead(200); return res.end(robots); }
      if (req.url === '/boom') { res.writeHead(500); return res.end('x'); }
      res.writeHead(200, { 'content-type': 'text/html' }); res.end(page);
    });
    hook = http.createServer((req, res) => {
      let body = ''; req.on('data', (c) => (body += c));
      req.on('end', () => { received.push({ headers: req.headers, body }); res.writeHead(200); res.end('ok'); });
    });
    await Promise.all([site, hook].map((s) => new Promise<void>((r) => s.listen(0, '127.0.0.1', r))));
    base = `http://127.0.0.1:${(site.address() as AddressInfo).port}`;
    hookUrl = `http://127.0.0.1:${(hook.address() as AddressInfo).port}/h`;
  });
  afterAll(async () => {
    site.close(); hook.close();
    const { prisma } = await import('../lib/db');
    await prisma.$disconnect();
  });

  it('records baseline, detects change, delivers verified webhook, suspends failing site', async () => {
    const { prisma } = await import('../lib/db');
    const { runMunicipalScraper, runAllActive } = await import('../lib/scraper/engine');
    const { encryptSecret } = await import('../lib/security/crypto');
    const { verifySignature } = await import('../lib/notifications/webhook');
    await prisma.webhookEndpoint.deleteMany(); await prisma.monitoredSite.deleteMany();

    const secret = 'integration-secret-1234';
    await prisma.webhookEndpoint.create({ data: { url: hookUrl, secret: encryptSecret(secret) } });
    const s = await prisma.monitoredSite.create({ data: { name: 'T', url: `${base}/page`, selector: '#o' } });

    expect(await runMunicipalScraper(s.id)).toMatchObject({ ok: true, changed: true, baseline: true });
    expect(await runMunicipalScraper(s.id)).toMatchObject({ ok: true, changed: false });
    expect(received).toHaveLength(0);

    page = '<div id="o"><p>Sec 1. Parking limit 2h.</p><p>Sec 2. No overnight parking.</p></div>';
    expect(await runMunicipalScraper(s.id)).toMatchObject({ ok: true, changed: true, baseline: false });
    expect(received).toHaveLength(1);
    const d = received[0];
    expect(verifySignature(d.body, secret, String(d.headers['x-icomply-signature']), String(d.headers['x-icomply-timestamp']))).toBe(true);
    expect(JSON.parse(d.body)).toMatchObject({ event: 'change', siteName: 'T' });
    const log = await prisma.changeLog.findFirst({ where: { monitoredSiteId: s.id, isBaseline: false } });
    expect(log?.addedText).toContain('No overnight parking.');
    expect(await prisma.webhookDelivery.count({ where: { success: true } })).toBe(1);

    // not due again immediately
    expect((await runAllActive()).length).toBe(0);

    const bad = await prisma.monitoredSite.create({ data: { name: 'Bad', url: `${base}/boom`, selector: '#o' } });
    for (let i = 0; i < 5; i++) await runMunicipalScraper(bad.id);
    const after = await prisma.monitoredSite.findUnique({ where: { id: bad.id } });
    expect(after).toMatchObject({ status: 'ERROR', consecutiveFailures: 5 });
    expect(received.some((r) => JSON.parse(r.body).event === 'site_error')).toBe(true);
  }, 60000);
});
