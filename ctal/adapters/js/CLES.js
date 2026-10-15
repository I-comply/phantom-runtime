import { randomUUID } from 'node:crypto';
import { signObject, verifyObject } from './crypto.js';

/** CLES issues signed entitlements and validates them against trusted issuer keys. */
export class CLES {
  constructor({ issuer, privateKeyPem, keyId = 'cles-ed25519-v1', publicKeys = {}, revocations = new Set(), clock = () => Date.now() } = {}) {
    if (!issuer) throw new Error('CLES issuer is required');
    this.issuer = issuer;
    this.privateKeyPem = privateKeyPem;
    this.keyId = keyId;
    this.publicKeys = publicKeys;
    this.revocations = revocations;
    this.clock = clock;
  }

  issue({ subject, product, features, ttlMs, deployment = 'production', maxActivations = 1, metadata = {} }) {
    if (!this.privateKeyPem) throw new Error('CLES signing private key is required');
    if (!subject || !product || !Array.isArray(features) || features.length === 0) throw new TypeError('subject, product, and at least one feature are required');
    if (!Number.isSafeInteger(ttlMs) || ttlMs <= 0) throw new TypeError('ttlMs must be a positive integer');
    if (!Number.isSafeInteger(maxActivations) || maxActivations < 1) throw new TypeError('maxActivations must be a positive integer');
    const issuedAt = this.clock();
    const payload = {
      schemaVersion: '1', licenseId: randomUUID(), issuer: this.issuer, subject, product,
      features: [...new Set(features)].sort(), deployment, maxActivations,
      issuedAt, notBefore: issuedAt, expiresAt: issuedAt + ttlMs,
      keyId: this.keyId, metadata
    };
    return { ...payload, signature: signObject(payload, this.privateKeyPem) };
  }

  revoke(licenseId) { this.revocations.add(licenseId); }

  verify(license, { subject, product, feature, deployment, now = this.clock() } = {}) {
    const deny = code => ({ authorized: false, code, licenseId: license?.licenseId ?? null });
    if (!license || license.schemaVersion !== '1') return deny('UNSUPPORTED_LICENSE_SCHEMA');
    const { signature, ...payload } = license;
    const key = this.publicKeys[payload.keyId];
    if (!key) return deny('UNKNOWN_ISSUER_KEY');
    if (!verifyObject(payload, signature, key)) return deny('INVALID_LICENSE_SIGNATURE');
    if (payload.issuer !== this.issuer) return deny('ISSUER_MISMATCH');
    if (this.revocations.has(payload.licenseId)) return deny('LICENSE_REVOKED');
    if (!Number.isSafeInteger(payload.issuedAt) || !Number.isSafeInteger(payload.notBefore) || !Number.isSafeInteger(payload.expiresAt) || payload.notBefore > now || payload.expiresAt <= now || payload.expiresAt <= payload.issuedAt) return deny('LICENSE_NOT_CURRENT');
    if (subject !== undefined && payload.subject !== subject) return deny('SUBJECT_MISMATCH');
    if (product !== undefined && payload.product !== product) return deny('PRODUCT_MISMATCH');
    if (deployment !== undefined && payload.deployment !== deployment) return deny('DEPLOYMENT_MISMATCH');
    if (feature !== undefined && !payload.features.includes(feature)) return deny('FEATURE_NOT_ENTITLED');
    return { authorized: true, code: 'LICENSE_VALID', licenseId: payload.licenseId, subject: payload.subject, product: payload.product, features: payload.features, expiresAt: payload.expiresAt, maxActivations: payload.maxActivations };
  }
}
