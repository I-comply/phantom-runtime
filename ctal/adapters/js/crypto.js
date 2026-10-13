// crypto.js: signature format used by AQPD.js and CLES.js in CTAL.
// The original module was not available, and no licenses had been issued before, so this file DEFINES the format:
//   canonical(obj) = JSON with object keys sorted (code-unit order), no whitespace, undefined-valued keys omitted;
//   signature      = base64url( Ed25519( UTF-8(canonical(payload)) ) ), keys as PEM (PKCS8 private / SPKI public).
// Independent re-implementation + cross-check: ctal/tests/test_online.py (Python verifies JS-issued licenses).
// If an existing deployment has licenses signed by a different original crypto.js, those will not verify here.
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
