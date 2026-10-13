// CTAL <-> AQPD/CLES bridge. One JSON request on stdin, one JSON response on stdout, then exit.
// Never prints key material or exception messages. Scope arguments to CLES.verify are REQUIRED here because
// CLES.verify() itself skips any scope check whose argument is omitted.
import { readFileSync } from 'node:fs';
import { AQPD, verifyAssessment } from './AQPD.js';
import { CLES } from './CLES.js';

const MAX_IN = 2_000_000;
const PRE_SIGNATURE = new Set(['UNSUPPORTED_LICENSE_SCHEMA', 'UNKNOWN_ISSUER_KEY', 'INVALID_LICENSE_SIGNATURE']);
const isStr = (v) => typeof v === 'string' && v.length > 0;

async function readStdin() {
  const chunks = []; let n = 0;
  for await (const c of process.stdin) { n += c.length; if (n > MAX_IN) throw new Error('INPUT_TOO_LARGE'); chunks.push(c); }
  return Buffer.concat(chunks).toString('utf8');
}
const done = (o) => { process.stdout.write(JSON.stringify(o)); };

try {
  const req = JSON.parse(await readStdin());
  if (req.op === 'aqpd.assess') {
    for (const k of ['content_b64', 'key_id', 'private_key_path', 'public_key_pem', 'source', 'workflow']) {
      if (!isStr(req[k])) { done({ ok: false, error: 'BAD_REQUEST:' + k }); process.exit(0); }
    }
    const bytes = Buffer.from(req.content_b64, 'base64');
    if (bytes.length > 1_000_000) { done({ ok: false, error: 'INPUT_TOO_LARGE' }); process.exit(0); }
    const opts = { privateKeyPem: readFileSync(req.private_key_path, 'utf8'), keyId: req.key_id };
    for (const [k, j] of [['max_bytes', 'maxBytes'], ['review_threshold', 'reviewThreshold'], ['deny_threshold', 'denyThreshold']]) {
      if (req[k] !== undefined && req[k] !== null) opts[j] = req[k];
    }
    const assessment = new AQPD(opts).assess({ content: bytes, source: req.source, workflow: req.workflow, provenance: { via: 'ctal' } });
    const v = verifyAssessment(assessment, { publicKeys: { [req.key_id]: req.public_key_pem }, content: bytes });
    done(v.valid ? { ok: true, assessment } : { ok: false, error: 'ASSESSMENT_UNVERIFIED:' + v.code });
  } else if (req.op === 'cles.verify') {
    for (const k of ['issuer', 'subject', 'product', 'deployment', 'feature']) {
      if (!isStr(req[k])) { done({ ok: false, error: 'BAD_REQUEST:' + k }); process.exit(0); }
    }
    if (!Number.isSafeInteger(req.now) || typeof req.license !== 'object' || req.license === null ||
        typeof req.public_keys !== 'object' || !Array.isArray(req.revoked)) { done({ ok: false, error: 'BAD_REQUEST' }); process.exit(0); }
    const cles = new CLES({ issuer: req.issuer, publicKeys: req.public_keys, revocations: new Set(req.revoked), clock: () => req.now });
    const result = cles.verify(req.license, { subject: req.subject, product: req.product, feature: req.feature, deployment: req.deployment, now: req.now });
    const l = req.license;
    const summary = PRE_SIGNATURE.has(result.code) ? null : {
      licenseId: l.licenseId, issuer: l.issuer, keyId: l.keyId, notBefore: l.notBefore, expiresAt: l.expiresAt,
      expired: Number.isSafeInteger(l.expiresAt) && l.expiresAt <= req.now
    };
    done({ ok: true, result, license: summary });
  } else {
    done({ ok: false, error: 'UNKNOWN_OP' });
  }
} catch (e) {
  done({ ok: false, error: 'BRIDGE_EXCEPTION:' + (e && e.name ? e.name : 'Error') });
}
