import { redirect } from 'next/navigation';
import { prisma } from '@/lib/db';
import { btn, field } from '@/lib/ui';
import { INTERVALS, validateTarget } from '@/lib/validate';

async function addSite(formData: FormData) {
  'use server';
  const name = String(formData.get('name') ?? '').trim();
  const url = String(formData.get('url') ?? '').trim();
  const selector = String(formData.get('selector') ?? '').trim();
  const intervalMinutes = Number(formData.get('interval'));
  let error: string | null = null;
  try {
    if (!INTERVALS.includes(intervalMinutes)) throw new Error('Invalid interval');
    const normalized = await validateTarget(name, url, selector);
    await prisma.monitoredSite.upsert({
      where: { url: normalized },
      update: { name, selector, intervalMinutes, status: 'ACTIVE', consecutiveFailures: 0, lastError: null, lastHash: null, lastText: null },
      create: { name, url: normalized, selector, intervalMinutes },
    });
  } catch (e: any) {
    error = e.message;
  }
  redirect(error ? `/dashboard/configure?error=${encodeURIComponent(error)}` : '/dashboard');
}

export default function ConfigurePage({ searchParams }: { searchParams: { error?: string } }) {
  return (
    <main style={{ maxWidth: 560, margin: '0 auto', padding: 32 }}>
      <h1>Add Monitored Target</h1>
      {searchParams.error && <p style={{ color: '#b91c1c' }}>{searchParams.error}</p>}
      <form action={addSite}>
        <label>Name<input name="name" required maxLength={200} style={field} /></label>
        <label>URL<input name="url" type="url" required style={field} /></label>
        <label>CSS Selector<input name="selector" required maxLength={500} style={field} /></label>
        <label>Check interval
          <select name="interval" defaultValue="360" style={field}>
            <option value="60">Hourly</option><option value="360">Every 6 hours</option><option value="1440">Daily</option>
          </select>
        </label>
        <button type="submit" style={btn()}>Save</button>{' '}
        <a href="/dashboard">Cancel</a>
      </form>
    </main>
  );
}
