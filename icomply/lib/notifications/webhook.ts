import axios from 'axios';
import crypto from 'crypto';
import { assertPublicUrl, safeLookup } from '../security/ssrf';

export interface WebhookPayload {
  event: 'change' | 'site_error';
  changeLogId: string | null;
  siteName: string;
  siteUrl: string;
  newHash: string | null;
  diffSummary: string;
  detectedAt: string;
}

export const SIGNATURE_TOLERANCE_SEC = 300;

export function signPayload(body: string, secret: string, timestamp: number): string {
  return 'sha256=' + crypto.createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex');
}

export function verifySignature(
  body: string,
  secret: string,
  signature: string | null,
  timestampHeader: string | null,
  nowSec = Math.floor(Date.now() / 1000),
): boolean {
  const ts = Number(timestampHeader);
  if (!signature || !Number.isInteger(ts) || Math.abs(nowSec - ts) > SIGNATURE_TOLERANCE_SEC) return false;
  const a = Buffer.from(signature);
  const b = Buffer.from(signPayload(body, secret, ts));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

export function backoffMs(attempt: number, base = 500): number {
  return base * 2 ** (attempt - 1);
}

export async function dispatchWebhook(endpointUrl: string, payload: WebhookPayload, secret: string) {
  await assertPublicUrl(endpointUrl);
  const body = JSON.stringify(payload);
  const ts = Math.floor(Date.now() / 1000);
  const res = await axios.post(endpointUrl, body, {
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'iComply-Webhook-Dispatcher/1.0',
      'X-iComply-Timestamp': String(ts),
      'X-iComply-Signature': signPayload(body, secret, ts),
    },
    timeout: 10000,
    maxRedirects: 0,
    lookup: safeLookup as any,
  });
  return { status: res.status };
}

export async function dispatchWithRetry(
  endpointUrl: string,
  payload: WebhookPayload,
  secret: string,
  maxAttempts = 3,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
) {
  let lastError = '';
  let httpStatus: number | undefined;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const { status } = await dispatchWebhook(endpointUrl, payload, secret);
      return { success: true, attempts: attempt, httpStatus: status, error: null as string | null };
    } catch (e: any) {
      httpStatus = e.response?.status;
      lastError = e.response ? `HTTP ${e.response.status}` : e.message;
      // 4xx (except 408/429) will not succeed on retry
      if (httpStatus && httpStatus >= 400 && httpStatus < 500 && httpStatus !== 408 && httpStatus !== 429) {
        return { success: false, attempts: attempt, httpStatus, error: lastError };
      }
      if (attempt < maxAttempts) await sleep(backoffMs(attempt));
    }
  }
  return { success: false, attempts: maxAttempts, httpStatus, error: lastError };
}
