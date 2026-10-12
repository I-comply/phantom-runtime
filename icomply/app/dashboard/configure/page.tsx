import { redirect } from 'next/navigation';
import { prisma } from '@/lib/db';

async function addSite(formData: FormData) {
  'use server';
  const name = String(formData.get('name') ?? '').trim();
  const url = String(formData.get('url') ?? '').trim();
  const selector = String(formData.get('selector') ?? '').trim();
  const parsed = new URL(url);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('URL must be http(s)');
  if (!name || !selector) throw new Error('Name and selector are required');
  await prisma.monitoredSite.upsert({
    where: { url: parsed.toString() },
    update: { name, selector },
    create: { name, url: parsed.toString(), selector },
  });
  redirect('/dashboard');
}

const field = { display: 'block', width: '100%', padding: 8, margin: '4px 0 16px', boxSizing: 'border-box' as const };

export default function ConfigurePage() {
  return (
    <main style={{ maxWidth: 560, margin: '0 auto', padding: 32 }}>
      <h1>Add Monitored Target</h1>
      <form action={addSite}>
        <label>Name<input name="name" required style={field} /></label>
        <label>URL<input name="url" type="url" required style={field} /></label>
        <label>CSS Selector<input name="selector" required style={field} /></label>
        <button type="submit" style={{ background: '#2563eb', color: '#fff', border: 0, padding: '8px 16px', borderRadius: 8 }}>Save</button>
      </form>
    </main>
  );
}
