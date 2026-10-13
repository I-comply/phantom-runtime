import { prisma } from '../db';
import { decryptSecret } from '../security/crypto';
import { dispatchWithRetry, WebhookPayload } from './webhook';

async function deliverAll(payload: WebhookPayload, ref: { changeLogId?: string }) {
  const endpoints = await prisma.webhookEndpoint.findMany({ where: { active: true } });
  await Promise.all(
    endpoints.map(async (ep) => {
      const r = await dispatchWithRetry(ep.url, payload, decryptSecret(ep.secret));
      await prisma.webhookDelivery.create({
        data: {
          endpointId: ep.id,
          event: payload.event,
          changeLogId: ref.changeLogId,
          success: r.success,
          httpStatus: r.httpStatus,
          attempts: r.attempts,
          error: r.error,
        },
      });
    }),
  );
}

export function notifyChange(
  log: { id: string; newHash: string; diffSummary: string | null; detectedAt: Date },
  site: { name: string; url: string },
) {
  return deliverAll({
    event: 'change',
    changeLogId: log.id,
    siteName: site.name,
    siteUrl: site.url,
    newHash: log.newHash,
    diffSummary: log.diffSummary ?? '',
    detectedAt: log.detectedAt.toISOString(),
  }, { changeLogId: log.id });
}

export function notifySiteError(site: { name: string; url: string }, error: string) {
  return deliverAll({
    event: 'site_error',
    changeLogId: null,
    siteName: site.name,
    siteUrl: site.url,
    newHash: null,
    diffSummary: `Monitoring suspended after repeated failures: ${error}`,
    detectedAt: new Date().toISOString(),
  }, {});
}
