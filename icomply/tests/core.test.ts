import { describe, expect, it } from 'vitest';
import { isPrivateIp, assertPublicUrl } from '../lib/security/ssrf';
import { extractText, hashText, summarizeDiff, validateSelector } from '../lib/scraper/extract';
import { backoffMs, dispatchWithRetry, signPayload, verifySignature } from '../lib/notifications/webhook';

describe('ssrf', () => {
  it.each(['127.0.0.1', '10.1.2.3', '172.16.0.1', '192.168.1.1', '169.254.169.254', '100.64.0.1', '::1', 'fd00::1', 'fe80::1', '::ffff:127.0.0.1', '::ffff:7f00:1'])(
    'blocks %s', (ip) => expect(isPrivateIp(ip)).toBe(true));
  it.each(['8.8.8.8', '1.1.1.1', '172.32.0.1', '2606:4700::1111'])('allows %s', (ip) => expect(isPrivateIp(ip)).toBe(false));
  it('rejects bad schemes, credentials, localhost, metadata IP', async () => {
    await expect(assertPublicUrl('file:///etc/passwd')).rejects.toThrow();
    await expect(assertPublicUrl('http://user:pw@example.com')).rejects.toThrow();
    await expect(assertPublicUrl('http://localhost:3000')).rejects.toThrow();
    await expect(assertPublicUrl('http://169.254.169.254/latest')).rejects.toThrow();
    await expect(assertPublicUrl('https://example.com/a')).resolves.toBeInstanceOf(URL);
  });
});

describe('extract', () => {
  const html = '<div id="o"><p>Sec 1.  Parking</p><script>x()</script><p>Sec 2.</p></div>';
  it('normalizes and strips scripts', () => expect(extractText(html, '#o')).toBe('Sec 1. Parking Sec 2.'));
  it('hash is stable', () => expect(hashText('a')).toBe(hashText('a')));
  it('validates selectors', () => {
    expect(() => validateSelector('div > p')).not.toThrow();
    expect(() => validateSelector('div[')).toThrow();
  });
  it('summarizes diff', () => {
    expect(summarizeDiff(null, 'abc')).toMatch(/Baseline/);
    const s = summarizeDiff('One. Two.', 'One. Three.');
    expect(s).toMatch(/1 segment\(s\) added, 1 removed/);
    expect(s).toMatch(/Three\./);
  });
});

describe('webhook signing', () => {
  const body = '{"a":1}';
  const now = 1_700_000_000;
  it('verifies valid signature', () =>
    expect(verifySignature(body, 's3cret', signPayload(body, 's3cret', now), String(now), now)).toBe(true));
  it('rejects wrong secret, tampered body, stale timestamp, missing', () => {
    const sig = signPayload(body, 's3cret', now);
    expect(verifySignature(body, 'other', sig, String(now), now)).toBe(false);
    expect(verifySignature('{"a":2}', 's3cret', sig, String(now), now)).toBe(false);
    expect(verifySignature(body, 's3cret', sig, String(now), now + 301)).toBe(false);
    expect(verifySignature(body, 's3cret', null, String(now), now)).toBe(false);
  });
  it('backs off exponentially', () => expect([1, 2, 3].map((a) => backoffMs(a))).toEqual([500, 1000, 2000]));
  it('does not retry non-retryable URL failure beyond attempts', async () => {
    const sleeps: number[] = [];
    const r = await dispatchWithRetry('http://localhost/x', { event: 'change', changeLogId: '1', siteName: 'a', siteUrl: 'b', newHash: 'c', diffSummary: '', detectedAt: '' }, 's', 3, async (ms) => { sleeps.push(ms); });
    expect(r.success).toBe(false);
    expect(r.attempts).toBe(3);
    expect(sleeps).toEqual([500, 1000]);
  });
});
