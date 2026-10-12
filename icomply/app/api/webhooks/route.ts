import crypto from 'crypto';
import { NextResponse } from 'next/server';
import { signPayload } from '@/lib/notifications/webhook';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  const secret = process.env.ICOMPLY_WEBHOOK_SECRET;
  if (!secret) {
    return NextResponse.json({ error: 'Webhook secret not configured' }, { status: 503 });
  }

  const raw = await request.text();
  const provided = request.headers.get('x-icomply-signature') ?? '';
  const expected = signPayload(raw, secret);
  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
  }

  let body: any;
  try {
    body = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  if (!body.siteName || !body.newHash) {
    return NextResponse.json({ error: 'Invalid payload structure' }, { status: 400 });
  }

  console.log(`[Webhook Received] target: ${body.siteName}`);
  return NextResponse.json({ received: true, timestamp: new Date().toISOString() });
}
