import { randomUUID } from 'node:crypto';
import { sha256, signObject, verifyObject } from './crypto.js';

const DEFAULT_RULES = [
  { id: 'PROMPT_OVERRIDE', severity: 'high', pattern: /(?:ignore|disregard|override)\s+(?:all\s+)?(?:previous|prior|system|developer)\s+(?:instructions|rules|messages)/i, reason: 'Instruction-hierarchy override attempt' },
  { id: 'SECRET_EXFILTRATION', severity: 'critical', pattern: /(?:reveal|print|dump|exfiltrate|send)\s+(?:the\s+)?(?:secret|system prompt|api key|private key|credentials)/i, reason: 'Potential secret disclosure request' },
  { id: 'TOOL_AUTHORITY_ABUSE', severity: 'high', pattern: /(?:bypass|disable|evade)\s+(?:security|authentication|authorization|policy|safety)/i, reason: 'Security control bypass language' },
  { id: 'UNTRUSTED_INSTRUCTION_MARKER', severity: 'medium', pattern: /\b(?:BEGIN|START)\s+(?:UNTRUSTED|MALICIOUS)\s+(?:INPUT|CONTENT)\b/i, reason: 'Explicit untrusted-content marker' }
];
const SCORE = { low: 0, medium: 25, high: 55, critical: 90 };

export class AQPD {
  constructor({ privateKeyPem, keyId = 'aqpd-ed25519-v1', rules = DEFAULT_RULES, maxBytes = 1_000_000, reviewThreshold = 25, denyThreshold = 80 } = {}) {
    this.privateKeyPem = privateKeyPem;
    this.keyId = keyId;
    this.rules = rules;
    this.maxBytes = maxBytes;
    this.reviewThreshold = reviewThreshold;
    this.denyThreshold = denyThreshold;
  }

  assess({ content, source = 'unspecified', provenance = {}, workflow = 'default', metadata = {} }) {
    if (typeof content !== 'string' && !Buffer.isBuffer(content)) throw new TypeError('content must be a string or Buffer');
    const bytes = Buffer.isBuffer(content) ? content : Buffer.from(content, 'utf8');
    const text = bytes.toString('utf8');
    const findings = [];
    let score = 0;

    if (bytes.byteLength > this.maxBytes) {
      findings.push({ ruleId: 'INPUT_TOO_LARGE', severity: 'critical', reason: `Input exceeds configured ${this.maxBytes}-byte limit`, start: null, end: null });
      score = 100;
    }
    for (const rule of this.rules) {
      rule.pattern.lastIndex = 0;
      const match = rule.pattern.exec(text);
      if (match) {
        findings.push({ ruleId: rule.id, severity: rule.severity, reason: rule.reason, start: match.index, end: match.index + match[0].length });
        score = Math.min(100, score + SCORE[rule.severity]);
      }
    }
    if (!source || source === 'unspecified') {
      findings.push({ ruleId: 'MISSING_SOURCE', severity: 'medium', reason: 'Input source was not identified', start: null, end: null });
      score = Math.min(100, score + 25);
    }
    const decision = score >= this.denyThreshold ? 'deny' : score >= this.reviewThreshold ? 'review' : 'allow';
    const issuedAt = Date.now();
    const payload = {
      contractVersion: '1', assessmentId: randomUUID(), contentDigest: sha256(bytes),
      decision, score, findings, source, provenance, workflow, metadata,
      policyVersion: 'aqpd-policy-1.0.0', issuedAt, expiresAt: issuedAt + 5 * 60_000, keyId: this.keyId
    };
    if (!this.privateKeyPem) throw new Error('AQPD signing private key is required to issue verifiable assessments');
    return { ...payload, signature: signObject(payload, this.privateKeyPem) };
  }
}

export function verifyAssessment(assessment, { publicKeys, content, now = Date.now(), maxLifetimeMs = 5 * 60_000 } = {}) {
  const fail = code => ({ valid: false, code });
  if (!assessment || assessment.contractVersion !== '1') return fail('UNSUPPORTED_CONTRACT');
  const { signature, ...payload } = assessment;
  if (!Number.isSafeInteger(payload.issuedAt) || !Number.isSafeInteger(payload.expiresAt) || payload.issuedAt > now || payload.expiresAt <= now || payload.expiresAt <= payload.issuedAt || payload.expiresAt - payload.issuedAt > maxLifetimeMs) return fail('ASSESSMENT_TIME_INVALID');
  if (content !== undefined && sha256(Buffer.isBuffer(content) ? content : Buffer.from(content, 'utf8')) !== payload.contentDigest) return fail('CONTENT_DIGEST_MISMATCH');
  const key = publicKeys?.[payload.keyId];
  if (!key) return fail('UNKNOWN_AQPD_KEY');
  if (!verifyObject(payload, signature, key)) return fail('INVALID_AQPD_SIGNATURE');
  return { valid: true, code: 'ASSESSMENT_VERIFIED', decision: payload.decision, score: payload.score };
}
