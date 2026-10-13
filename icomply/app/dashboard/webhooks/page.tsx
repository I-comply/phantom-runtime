import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { prisma } from '@/lib/db';
import { encryptSecret } from '@/lib/security/crypto';
import { assertPublicUrl } from '@/lib/security/ssrf';
import { btn, card, field } from '@/lib/ui';

export const dynamic = 'force-dynamic';

async function addEndpoint(formData: FormData) {
  'use server';
  const url = String(formData.get('url') ?? '').trim();
  const secret = String(formData.get('secret') ?? '');
  let error: string | null = null;
  try {
    if (secret.length < 16) throw new Error('Secret must be at least 16 characters');
    const u = (await assertPublicUrl(url)).toString();
    await prisma.webhookEndpoint.upsert({ where: { url: u }, update: { secret: encryptSecret(secret), active: true }, create: { url: u, secret: encryptSecret(secret) } });
  } catch (e: any) {
    error = e.message;
  }
  if (error) redirect(`/dashboard/webhooks?error=${encodeURIComponent(error)}`);
  revalidatePath('/dashboard/webhooks');
}

async function removeEndpoint(formData: FormData) {
  'use server';
  await prisma.webhookEndpoint.delete({ where: { id: String(formData.get('id')) } });
  revalidatePath('/dashboard/webhooks');
}

export default async function WebhooksPage({ searchParams }: { searchParams: { error?: string } }) {
  const endpoints = await prisma.webhookEndpoint.findMany({
    orderBy: { createdAt: 'desc' },
    include: { deliveries: { orderBy: { createdAt: 'desc' }, take: 3 } },
  });
  return (
    <main style={{ maxWidth: 760, margin: '0 auto', padding: 32 }}>
      <a href="/dashboard">&larr; Dashboard</a>
      <h1>Webhook Endpoints</h1>
      <p style={{ fontSize: 13, color: '#6b7280' }}>
        Events: <code>change</code>, <code>site_error</code>. Deliveries are signed: <code>X-iComply-Signature = sha256=HMAC(secret, timestamp + "." + body)</code>, with <code>X-iComply-Timestamp</code>.
      </p>
      {searchParams.error && <p style={{ color: '#b91c1c' }}>{searchParams.error}</p>}
      <form action={addEndpoint}>
        <label>Endpoint URL<input name="url" type="url" required style={field} /></label>
        <label>Signing secret (min 16 chars)<input name="secret" type="password" required minLength={16} style={field} /></label>
        <button style={btn()}>Save endpoint</button>
      </form>
      <section style={card}>
        {endpoints.length === 0 && <div style={{ padding: 24, color: '#6b7280' }}>No endpoints configured.</div>}
        {endpoints.map((e) => (
          <div key={e.id} style={{ padding: 16, borderTop: '1px solid #f3f4f6' }}>
            <div style={{ wordBreak: 'break-all' }}>{e.url}</div>
            <ul style={{ fontSize: 12, color: '#374151' }}>
              {e.deliveries.map((d) => (
                <li key={d.id}>{d.createdAt.toISOString()} [{d.event}] {d.success ? 'OK' : `FAILED (${d.error})`} after {d.attempts} attempt(s)</li>
              ))}
            </ul>
            <form action={removeEndpoint}><input type="hidden" name="id" value={e.id} /><button style={btn('#b91c1c')}>Remove</button></form>
          </div>
        ))}
      </section>
    </main>
  );
}
