import dns from 'dns';
import net from 'net';

const allowPrivate = () => process.env.ICOMPLY_ALLOW_PRIVATE_TARGETS === 'true';

export function isPrivateIp(ip: string): boolean {
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split('.').map(Number);
    return (
      a === 0 || a === 10 || a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 192 && b === 0) ||
      (a === 198 && (b === 18 || b === 19)) ||
      a >= 224
    );
  }
  if (net.isIPv6(ip)) {
    const l = ip.toLowerCase();
    if (l === '::' || l === '::1') return true;
    if (l.startsWith('::ffff:')) {
      const rest = l.slice(7);
      return net.isIPv4(rest) ? isPrivateIp(rest) : true;
    }
    return l.startsWith('fc') || l.startsWith('fd') || /^fe[89ab]/.test(l) || l.startsWith('ff');
  }
  return true;
}

/** Validates scheme and, for IP-literal hosts, the address. Hostnames are checked at connect time by safeLookup. */
export async function assertPublicUrl(raw: string): Promise<URL> {
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    throw new Error('Invalid URL');
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error('URL must be http(s)');
  if (u.username || u.password) throw new Error('URL must not contain credentials');
  if (allowPrivate()) return u;
  const host = u.hostname.replace(/^\[|\]$/g, '');
  if (net.isIP(host) && isPrivateIp(host)) throw new Error('Target address is not publicly routable');
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.internal')) {
    throw new Error('Target host is not allowed');
  }
  return u;
}

/** DNS lookup that rejects private/internal resolutions at connect time (blocks DNS rebinding). */
export function safeLookup(hostname: string, options: any, cb: any) {
  dns.lookup(hostname, { ...options, all: true }, (err, addrs: any) => {
    if (err) return cb(err);
    const list = addrs as dns.LookupAddress[];
    if (!allowPrivate() && list.some((a) => isPrivateIp(a.address))) {
      return cb(new Error(`Target ${hostname} resolves to a non-public address`));
    }
    if (options?.all) return cb(null, list);
    return cb(null, list[0].address, list[0].family);
  });
}
