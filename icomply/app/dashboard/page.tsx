import { prisma } from '@/lib/db';

export const dynamic = 'force-dynamic';

async function getMonitoredSites() {
  try {
    return await prisma.monitoredSite.findMany({
      include: { changeLogs: { orderBy: { detectedAt: 'desc' }, take: 1 } },
      orderBy: { updatedAt: 'desc' },
    });
  } catch {
    return [];
  }
}

export default async function DashboardPage() {
  const sites = await getMonitoredSites();

  return (
    <main style={{ maxWidth: 960, margin: '0 auto', padding: 32 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #e5e7eb', paddingBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0 }}>iComply Control Panel</h1>
          <p style={{ margin: 0, fontSize: 14, color: '#6b7280' }}>Municipal Ordinance &amp; Compliance Monitoring</p>
        </div>
        <a href="/dashboard/configure" style={{ background: '#2563eb', color: '#fff', padding: '8px 16px', borderRadius: 8, textDecoration: 'none' }}>
          + Add Monitored Target
        </a>
      </header>

      <section style={{ marginTop: 24, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12 }}>
        <div style={{ padding: '16px 24px', borderBottom: '1px solid #f3f4f6', fontWeight: 600 }}>
          Active Municipal Targets ({sites.length})
        </div>
        {sites.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#6b7280' }}>
            No sites currently monitored. Add your first target to begin scraping.
          </div>
        ) : (
          sites.map((site) => (
            <div key={site.id} style={{ padding: 24, display: 'flex', justifyContent: 'space-between', gap: 16, borderTop: '1px solid #f3f4f6', flexWrap: 'wrap' }}>
              <div>
                <h3 style={{ margin: 0 }}>{site.name}</h3>
                <a href={site.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, color: '#2563eb', wordBreak: 'break-all' }}>
                  {site.url}
                </a>
                <p style={{ margin: 0, fontSize: 12, color: '#6b7280', fontFamily: 'monospace' }}>Selector: {site.selector}</p>
              </div>
              <div style={{ fontSize: 12, color: '#6b7280', textAlign: 'right' }}>
                <div style={{ fontWeight: 600, color: site.status === 'ACTIVE' ? '#166534' : '#854d0e' }}>{site.status}</div>
                <div>Last Checked: {site.lastChecked ? site.lastChecked.toISOString() : 'Never'}</div>
                <div>Last Change: {site.changeLogs[0] ? site.changeLogs[0].detectedAt.toISOString() : 'None'}</div>
              </div>
            </div>
          ))
        )}
      </section>
    </main>
  );
}
