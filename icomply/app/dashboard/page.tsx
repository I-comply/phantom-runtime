import { prisma } from '@/lib/db';
import { btn, card } from '@/lib/ui';
import { removeSite, runNow, setStatus } from './actions';

export const dynamic = 'force-dynamic';

const color = (s: string) => (s === 'ACTIVE' ? '#166534' : s === 'ERROR' ? '#b91c1c' : '#854d0e');

export default async function DashboardPage() {
  const sites = await prisma.monitoredSite.findMany({
    include: { changeLogs: { orderBy: { detectedAt: 'desc' }, take: 3 } },
    orderBy: { updatedAt: 'desc' },
  });

  return (
    <main style={{ maxWidth: 960, margin: '0 auto', padding: 32 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #e5e7eb', paddingBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ margin: 0 }}>iComply Control Panel</h1>
          <p style={{ margin: 0, fontSize: 14, color: '#6b7280' }}>Municipal Ordinance &amp; Compliance Monitoring</p>
        </div>
        <nav style={{ display: 'flex', gap: 8 }}>
          <a href="/dashboard/webhooks" style={{ ...btn('#4b5563'), textDecoration: 'none' }}>Webhooks</a>
          <a href="/dashboard/configure" style={{ ...btn(), textDecoration: 'none' }}>+ Add Target</a>
        </nav>
      </header>

      <section style={card}>
        <div style={{ padding: '16px 24px', fontWeight: 600 }}>Municipal Targets ({sites.length})</div>
        {sites.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#6b7280' }}>No targets yet. Add one to begin monitoring.</div>
        ) : (
          sites.map((s) => (
            <div key={s.id} style={{ padding: 24, borderTop: '1px solid #f3f4f6' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
                <div>
                  <h3 style={{ margin: 0 }}>{s.name}</h3>
                  <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, color: '#2563eb', wordBreak: 'break-all' }}>{s.url}</a>
                  <p style={{ margin: 0, fontSize: 12, color: '#6b7280', fontFamily: 'monospace' }}>Selector: {s.selector} · every {s.intervalMinutes}m · <a href={`/dashboard/sites/${s.id}`}>History</a></p>
                </div>
                <div style={{ fontSize: 12, color: '#6b7280', textAlign: 'right' }}>
                  <div style={{ fontWeight: 600, color: color(s.status) }}>{s.status}</div>
                  <div>Checked: {s.lastChecked ? s.lastChecked.toISOString() : 'Never'}</div>
                </div>
              </div>
              {s.lastError && (
                <p style={{ fontSize: 12, color: '#b91c1c' }}>Last error ({s.consecutiveFailures}x): {s.lastError}</p>
              )}
              {s.changeLogs.length > 0 && (
                <ul style={{ fontSize: 12, color: '#374151', paddingLeft: 18 }}>
                  {s.changeLogs.map((c) => (
                    <li key={c.id}>{c.detectedAt.toISOString()} {c.isBaseline ? '[baseline] ' : ''}{c.diffSummary}</li>
                  ))}
                </ul>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <form action={runNow}><input type="hidden" name="id" value={s.id} /><button style={btn()}>Run now</button></form>
                <form action={setStatus}>
                  <input type="hidden" name="id" value={s.id} />
                  <input type="hidden" name="status" value={s.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE'} />
                  <button style={btn('#4b5563')}>{s.status === 'ACTIVE' ? 'Pause' : 'Resume'}</button>
                </form>
                <form action={removeSite}><input type="hidden" name="id" value={s.id} /><button style={btn('#b91c1c')}>Delete</button></form>
              </div>
            </div>
          ))
        )}
      </section>
    </main>
  );
}
