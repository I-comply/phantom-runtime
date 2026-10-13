// RECONSTRUCTED MODULE (new, written by the CTAL implementer).
// AQPD.js and CLES.js import { sha256, signObject, verifyObject } from './crypto.js' but the original file was
// NOT included in the supplied archive. This minimal version uses Node's built-in Ed25519 over a sorted-key
// JSON serialization. It is NOT known to match the original canonicalization/signature encoding, so
// signatures produced by the original system (existing licenses/assessments) are UNVERIFIED against it.
// Replace with the original crypto.js when available and re-run ctal/tests.
import { createHash, createPrivateKey, createPublicKey, sign, verify } from 'node:crypto';

export const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

function canonical(value) {
  if (value === null) return 'null';
  switch (typeof value) {
    case 'string': return JSON.stringify(value);
    case 'boolean': return value ? 'true' : 'false';
    case 'number':
      if (!Number.isFinite(value)) throw new TypeError('non-finite number');
      return JSON.stringify(value);
    case 'object':
      if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
      return '{' + Object.keys(value).filter((k) => value[k] !== undefined).sort()
        .map((k) => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
    default: throw new TypeError('unsupported type in signed object');
  }
}

export function signObject(obj, privateKeyPem) {
  return sign(null, Buffer.from(canonical(obj), 'utf8'), createPrivateKey(privateKeyPem)).toString('base64url');
}

export function verifyObject(obj, signature, publicKeyPem) {
  try {
    if (typeof signature !== 'string') return false;
    return verify(null, Buffer.from(canonical(obj), 'utf8'), createPublicKey(publicKeyPem), Buffer.from(signature, 'base64url'));
  } catch {
    return false;
  }
}
