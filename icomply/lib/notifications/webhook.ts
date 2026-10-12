import axios from 'axios';
import crypto from 'crypto';

export interface WebhookPayload {
  siteName: string;
  siteUrl: string;
  newHash: string;
  diffSummary: string;
  detectedAt: string;
}

export function signPayload(body: string, secret: string): string {
  return crypto.createHmac('sha256', secret).update(body).digest('hex');
}

export async function dispatchWebhook(endpointUrl: string, payload: WebhookPayload, secret?: string) {
  const body = JSON.stringify(payload);
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'User-Agent': 'iComply-Webhook-Dispatcher/1.0',
  };
  if (secret) headers['X-iComply-Signature'] = signPayload(body, secret);

  try {
    const response = await axios.post(endpointUrl, body, { headers, timeout: 10000 });
    return { success: true, status: response.status };
  } catch (error: any) {
    const cause = error.response ? `HTTP ${error.response.status}` : error.message;
    throw new Error(`Failed to dispatch webhook to ${endpointUrl}. Cause: ${cause}`);
  }
}
