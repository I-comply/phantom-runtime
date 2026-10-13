import axios from 'axios';
import { assertPublicUrl, safeLookup } from '../security/ssrf';

const MAX_REDIRECTS = 3;
const MAX_BYTES = 5 * 1024 * 1024;
export const USER_AGENT = 'Mozilla/5.0 (Compatible; iComply-Sentinel/1.0; +https://icomply.local)';

export async function fetchRaw(url: string, opts: { timeout?: number; maxStatus?: number } = {}) {
  let current = url;
  for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
    await assertPublicUrl(current);
    const res = await axios.get<string>(current, {
      headers: { 'User-Agent': USER_AGENT, Accept: 'text/html,application/xhtml+xml,text/plain;q=0.8' },
      timeout: opts.timeout ?? 15000,
      maxRedirects: 0,
      maxContentLength: MAX_BYTES,
      maxBodyLength: MAX_BYTES,
      responseType: 'text',
      validateStatus: (s) => s < (opts.maxStatus ?? 400),
      lookup: safeLookup as any,
    });
    if (res.status >= 300 && res.status < 400) {
      const loc = res.headers.location;
      if (!loc) throw new Error(`HTTP ${res.status} redirect without Location`);
      current = new URL(loc, current).toString();
      continue;
    }
    return res;
  }
  throw new Error('Too many redirects');
}

export async function fetchHtml(url: string): Promise<string> {
  const res = await fetchRaw(url);
  const ct = String(res.headers['content-type'] ?? '');
  if (ct && !/html|xml|text/i.test(ct)) throw new Error(`Unsupported content type: ${ct}`);
  return res.data;
}
