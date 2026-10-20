import { NextRequest, NextResponse } from 'next/server';

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

const deny = (status: number, body: string, headers?: HeadersInit) =>
  new NextResponse(body, { status, headers });

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const prod = process.env.NODE_ENV === 'production';

  if (pathname.startsWith('/api/cron')) {
    const secret = process.env.CRON_SECRET;
    if (!secret) return deny(503, 'CRON_SECRET not configured');
    return safeEqual(req.headers.get('authorization') ?? '', `Bearer ${secret}`)
      ? NextResponse.next()
      : deny(401, 'Unauthorized');
  }

  // /dashboard: HTTP Basic auth
  const user = process.env.DASHBOARD_USER;
  const pass = process.env.DASHBOARD_PASSWORD;
  if (!user || !pass) {
    return prod ? deny(503, 'Dashboard credentials not configured') : NextResponse.next();
  }
  const h = req.headers.get('authorization') ?? '';
  if (h.startsWith('Basic ')) {
    try {
      const [u, ...rest] = atob(h.slice(6)).split(':');
      if (safeEqual(u, user) && safeEqual(rest.join(':'), pass)) return NextResponse.next();
    } catch (err) {
      // Malformed Basic credentials fall through to the 401 below.
      console.warn('middleware: invalid Authorization header', err instanceof Error ? err.message : err);
    }
  }
  return deny(401, 'Authentication required', { 'WWW-Authenticate': 'Basic realm="iComply"' });
}

export const config = { matcher: ['/dashboard/:path*', '/api/cron/:path*'] };
