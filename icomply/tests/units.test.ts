import { describe, expect, it } from 'vitest';
import { isAllowed } from '../lib/scraper/robots';
import { decryptSecret, encryptSecret } from '../lib/security/crypto';
import { diffSegments, isDue } from '../lib/scraper/extract';

process.env.ICOMPLY_ENCRYPTION_KEY = 'k'.repeat(40);

describe('robots', () => {
  const r = `User-agent: *\nDisallow: /private\nAllow: /private/public\nDisallow: /*.pdf$\n\nUser-agent: icomply-sentinel\nDisallow: /blocked\n`;
  it('prefers the specific UA group', () => {
    expect(isAllowed(r, '/blocked/x')).toBe(false);
    expect(isAllowed(r, '/private')).toBe(true); // `*` group ignored when specific group exists
  });
  it('longest match, wildcards, $', () => {
    const g = `User-agent: *\nDisallow: /private\nAllow: /private/public\nDisallow: /*.pdf$`;
    expect(isAllowed(g, '/private/a')).toBe(false);
    expect(isAllowed(g, '/private/public/a')).toBe(true);
    expect(isAllowed(g, '/x/a.pdf')).toBe(false);
    expect(isAllowed(g, '/x/a.pdf?z=1')).toBe(true);
    expect(isAllowed('User-agent: *\nDisallow:', '/anything')).toBe(true);
    expect(isAllowed('User-agent: *\nDisallow: /', '/anything')).toBe(false);
  });
});

describe('crypto', () => {
  it('round-trips and randomizes', () => {
    const a = encryptSecret('hunter2hunter2hunter2');
    expect(a).not.toContain('hunter2');
    expect(a).not.toBe(encryptSecret('hunter2hunter2hunter2'));
    expect(decryptSecret(a)).toBe('hunter2hunter2hunter2');
  });
  it('detects tampering', () => {
    const [v, iv, tag, ct] = encryptSecret('abcdefabcdefabcdef').split(':');
    const bad = Buffer.from(ct, 'base64'); bad[0] ^= 1;
    expect(() => decryptSecret([v, iv, tag, bad.toString('base64')].join(':'))).toThrow();
  });
});

describe('scheduling & diff', () => {
  const now = new Date('2026-01-01T12:00:00Z');
  it('isDue', () => {
    expect(isDue({ lastChecked: null, intervalMinutes: 60 }, now)).toBe(true);
    expect(isDue({ lastChecked: new Date('2026-01-01T11:30:00Z'), intervalMinutes: 60 }, now)).toBe(false);
    expect(isDue({ lastChecked: new Date('2026-01-01T10:59:30Z'), intervalMinutes: 60 }, now)).toBe(true);
  });
  it('diffSegments', () => {
    expect(diffSegments('A. B.', 'A. C.')).toEqual({ added: ['C.'], removed: ['B.'] });
  });
});
