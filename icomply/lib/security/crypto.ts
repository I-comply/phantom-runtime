import crypto from 'crypto';

function key(): Buffer {
  const k = process.env.ICOMPLY_ENCRYPTION_KEY;
  if (!k || k.length < 32) throw new Error('ICOMPLY_ENCRYPTION_KEY (min 32 chars) is required');
  return crypto.createHash('sha256').update(k).digest();
}

/** AES-256-GCM. Format: v1:<iv>:<tag>:<ciphertext> (base64). */
export function encryptSecret(plain: string): string {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key(), iv);
  const ct = Buffer.concat([c.update(plain, 'utf8'), c.final()]);
  return ['v1', iv.toString('base64'), c.getAuthTag().toString('base64'), ct.toString('base64')].join(':');
}

export function decryptSecret(stored: string): string {
  if (!stored.startsWith('v1:')) return stored; // legacy plaintext
  const [, iv, tag, ct] = stored.split(':');
  const d = crypto.createDecipheriv('aes-256-gcm', key(), Buffer.from(iv, 'base64'));
  d.setAuthTag(Buffer.from(tag, 'base64'));
  return Buffer.concat([d.update(Buffer.from(ct, 'base64')), d.final()]).toString('utf8');
}
