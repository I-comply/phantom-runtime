import { prisma } from '../db';
import { dispatchWithRetry } from './webhook';

export async function notifyChange(
  changeLog: { id: string; newHash: string; diffSummary: string | null; detectedAt: Date },
  site: { name: string; url: string },
) {
  const endpoints = await prisma.webhookEndpoint.findMany({ where: { active: true } });
  await Promise.all(
    endpoints.map(async (ep) => {
      const r = await dispatchWithRetry(ep.url, {
        changeLogId: changeLog.id,
        siteName: site.name,
        siteUrl: site.url,
        newHash: changeLog.newHash,
        diffSummary: changeLog.diffSummary ?? '',
        detectedAt: changeLog.detectedAt.toISOString(),
      }, ep.secret);
      await prisma.webhookDelivery.create({
        data: {
          endpointId: ep.id,
          changeLogId: changeLog.id,
          success: r.success,
          httpStatus: r.httpStatus,
          attempts: r.attempts,
          error: r.error,
        },
      });
    }),
  );
}
