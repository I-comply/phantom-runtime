import { notFound } from 'next/navigation';
import { prisma } from '@/lib/db';
import { card } from '@/lib/ui';

export const dynamic = 'force-dynamic';

const pre = { whiteSpace: 'pre-wrap' as const, fontSize: 12, margin: '4px 0', padding: 8, borderRadius: 6 };

export default async function SiteHistory({ params }: { params: { id: string } }) {
  const site = await prisma.monitoredSite.findUnique({
    where: { id: params.id },
    include: { changeLogs: { orderBy: { detectedAt: 'desc' }, take: 50 } },
  });
  if (!site) notFound();
  return (
    <main style={{ maxWidth: 860, margin: '0 auto', padding: 32 }}>
      <a href="/dashboard">&larr; Dashboard</a>
      <h1>{site.name}</h1>
      <p style={{ fontSize: 12, color: '#6b7280', wordBreak: 'break-all' }}>{site.url}</p>
      <section style={card}>
        {site.changeLogs.length === 0 && <div style={{ padding: 24, color: '#6b7280' }}>No changes recorded.</div>}
        {site.changeLogs.map((c) => (
          <div key={c.id} style={{ padding: 16, borderTop: '1px solid #f3f4f6' }}>
            <strong>{c.detectedAt.toISOString()}</strong> {c.isBaseline && '[baseline]'}
            <div style={{ fontSize: 12, color: '#374151' }}>{c.diffSummary}</div>
            {c.addedText && <pre style={{ ...pre, background: '#dcfce7' }}>{c.addedText}</pre>}
            {c.removedText && <pre style={{ ...pre, background: '#fee2e2' }}>{c.removedText}</pre>}
          </div>
        ))}
      </section>
    </main>
  );
}
