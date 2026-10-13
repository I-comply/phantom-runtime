import { fetchRaw } from './fetch';

const UA = 'icomply-sentinel';
const TTL_MS = 60 * 60 * 1000;
const cache = new Map<string, { at: number; body: string | null }>();

function matches(pattern: string, path: string): boolean {
  const re = '^' + pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\\\$$/, '$');
  return new RegExp(re).test(path);
}

/** RFC 9309 subset: group selection by UA, longest-match wins, Allow wins ties, `*` and `$`. */
export function isAllowed(robots: string, path: string, ua = UA): boolean {
  type Group = { agents: string[]; rules: { allow: boolean; path: string }[] };
  const groups: Group[] = [];
  let cur: Group | null = null;
  let lastWasAgent = false;
  for (const raw of robots.split(/\r?\n/)) {
    const line = raw.replace(/#.*/, '').trim();
    const i = line.indexOf(':');
    if (i < 0) continue;
    const k = line.slice(0, i).trim().toLowerCase();
    const v = line.slice(i + 1).trim();
    if (k === 'user-agent') {
      if (!cur || !lastWasAgent) {
        cur = { agents: [], rules: [] };
        groups.push(cur);
      }
      cur.agents.push(v.toLowerCase());
      lastWasAgent = true;
    } else {
      lastWasAgent = false;
      if ((k === 'allow' || k === 'disallow') && cur && v) cur.rules.push({ allow: k === 'allow', path: v });
    }
  }
  const u = ua.toLowerCase();
  let sel = groups.filter((g) => g.agents.some((a) => a !== '*' && u.includes(a)));
  if (!sel.length) sel = groups.filter((g) => g.agents.includes('*'));
  let best: { allow: boolean; len: number } | null = null;
  for (const r of sel.flatMap((g) => g.rules)) {
    if (!matches(r.path, path)) continue;
    const len = r.path.length;
    if (!best || len > best.len || (len === best.len && r.allow)) best = { allow: r.allow, len };
  }
  return best ? best.allow : true;
}

export async function assertRobotsAllowed(target: string): Promise<void> {
  if (process.env.ICOMPLY_RESPECT_ROBOTS === 'false') return;
  const u = new URL(target);
  const hit = cache.get(u.origin);
  let body: string | null;
  if (hit && Date.now() - hit.at < TTL_MS) {
    body = hit.body;
  } else {
    let res;
    try {
      res = await fetchRaw(`${u.origin}/robots.txt`, { timeout: 8000, maxStatus: 600 });
    } catch (e: any) {
      throw new Error(`robots.txt unavailable: ${e.message}`);
    }
    if (res.status >= 500) throw new Error(`robots.txt unavailable: HTTP ${res.status}`);
    body = res.status === 200 ? String(res.data) : null; // 4xx => no restrictions
    cache.set(u.origin, { at: Date.now(), body });
  }
  if (body && !isAllowed(body, u.pathname + u.search)) throw new Error('Blocked by robots.txt');
}
