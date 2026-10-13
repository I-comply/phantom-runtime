import { NextResponse } from 'next/server';
import { verifySignature } from '@/lib/notifications/webhook';

export const dynamic = 'force-dynamic';

/** Reference receiver for iComply webhook deliveries (HMAC + timestamp verified). */
export async function POST(request: Request) {
  const secret = process.env.ICOMPLY_WEBHOOK_SECRET;
  if (!secret) return NextResponse.json({ error: 'Webhook secret not configured' }, { status: 503 });

  const raw = await request.text();
  if (!verifySignature(raw, secret, request.headers.get('x-icomply-signature'), request.headers.get('x-icomply-timestamp'))) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
  }

  let body: any;
  try {
    body = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  if (!body.siteName || !['change', 'site_error'].includes(body.event)) {
    return NextResponse.json({ error: 'Invalid payload structure' }, { status: 400 });
  }
  console.log(`[Webhook Received] target: ${body.siteName}`);
  return NextResponse.json({ received: true, timestamp: new Date().toISOString() });
}
