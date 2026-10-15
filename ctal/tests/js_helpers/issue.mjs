// Test helper: issue a license with the supplied CLES.js (stdin JSON -> stdout license JSON).
import { readFileSync } from 'node:fs';
import { CLES } from '../../adapters/js/CLES.js';
const req = JSON.parse(readFileSync(0, 'utf8'));
const cles = new CLES({ issuer: req.issuer, privateKeyPem: readFileSync(req.private_key_path, 'utf8'), keyId: req.key_id, clock: () => req.now });
process.stdout.write(JSON.stringify(cles.issue({ subject: req.subject, product: req.product, features: req.features,
  ttlMs: req.ttl_ms, deployment: req.deployment, maxActivations: req.max_activations ?? 1 })));
