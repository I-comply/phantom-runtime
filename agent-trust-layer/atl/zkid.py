"""Zero-knowledge identity assertion: prove "I hold a credential committed as C whose permission set includes
tool T" with a Groth16 zk-SNARK, revealing none of: principal secret, tool-access/env tokens, session config,
or the rest of the permission set.

Circuit (public: C, M=2^t, challenge; private: secret, mask, salt):
    H1 = mimc(mask, salt);  C == mimc(secret, H1);  bit_t(mask) == 1;  challenge bound into the QAP.
`salt` = digest(session config, env/tool-access tokens). Verifier checks M is the claimed tool's selector and
that the nonce is fresh (Verifier below); the commitment C is registered at enrollment by the trusted issuer.
"""
import hashlib, json, os, secrets, time
from pathlib import Path
from . import groth16 as g
from .groth16 import R, CircuitBuilder

NBITS = 32
ROUNDS = 91


class ZKError(Exception):
    pass


def _h2f(*parts):
    h = hashlib.sha256(b"|".join(p if isinstance(p, bytes) else str(p).encode() for p in parts)).digest()
    return int.from_bytes(h, "big") % R


def _consts(rounds):
    return [_h2f(b"atl-zk-mimc", i) for i in range(rounds)]


def mimc_hash(x, k, rounds=ROUNDS):
    """Miyaguchi-Preneel over MiMC-x^7 (gcd(7, r-1)=1)."""
    x0, v = x % R, x % R
    for c in _consts(rounds):
        v = pow(v + k + c, 7, R)
    return (v + k + x0) % R


def _mimc_circ(cb, x, k, rounds):
    v = x
    for c in _consts(rounds):
        t = cb.add(v, k, cb.const(c))
        t2 = cb.mul(t, t); t4 = cb.mul(t2, t2); t6 = cb.mul(t4, t2)
        v = cb.mul(t6, t)
    return cb.add(v, k, x)


def build_circuit(w, rounds=ROUNDS):
    """w: dict(C, M, chal, secret, mask, salt). Structure is independent of values."""
    cb = CircuitBuilder()
    C, M, chal = cb.pub(w["C"]), cb.pub(w["M"]), cb.pub(w["chal"])
    secret, mask, salt = cb.priv(w["secret"]), cb.priv(w["mask"]), cb.priv(w["salt"])
    h1 = _mimc_circ(cb, mask, salt, rounds)
    cb.assert_eq(_mimc_circ(cb, secret, h1, rounds), C)
    sel = w["M"]
    bits, ssel, prods = [], [], []
    for i in range(NBITS):
        bi = cb.priv((w["mask"] >> i) & 1)
        si = cb.priv(1 if sel == 1 << i else 0)
        for x in (bi, si):
            cb.cons.append((x, cb.add(x, cb.const(-1)), {}))             # x*(x-1)=0
        bits.append(bi); ssel.append(si); prods.append(cb.mul(bi, si))
    cb.assert_eq(cb.add(*[cb.scale(b_, 1 << i) for i, b_ in enumerate(bits)]), mask)
    cb.assert_eq(cb.add(*[cb.scale(s_, 1 << i) for i, s_ in enumerate(ssel)]), M)
    cb.assert_eq(cb.add(*ssel), cb.const(1))
    cb.assert_eq(cb.add(*prods), cb.const(1))
    cb.mul(chal, chal)                                                    # binds challenge into the QAP
    return cb


_DUMMY = dict(C=0, M=1, chal=0, secret=0, mask=0, salt=0)


def secret_scalar(principal_secret_hex):
    return _h2f(b"atl-zk-secret", bytes.fromhex(principal_secret_hex))


def session_salt(session_config, env_tokens):
    blob = json.dumps({"cfg": session_config, "env": env_tokens}, sort_keys=True, separators=(",", ":"))
    return _h2f(b"atl-zk-salt", blob.encode())


def permission_mask(tool_names, granted):
    tools = sorted(tool_names)
    if len(tools) > NBITS:
        raise ZKError("too_many_tools")
    return sum(1 << i for i, t in enumerate(tools) if granted(t))


def tool_selector(tool_names, tool):
    tools = sorted(tool_names)
    if tool not in tools:
        raise ZKError("unknown_tool")
    return 1 << tools.index(tool)


def challenge_scalar(nonce, tenant, agent, tool):
    return _h2f(b"atl-zk-chal", nonce, tenant, agent, tool)


def commit(secret, mask, salt, rounds=ROUNDS):
    return mimc_hash(secret, mimc_hash(mask, salt, rounds), rounds)


class ZKIdentity:
    """Holds proving/verifying keys. `keydir` caches them; the proving key is only needed by provers."""

    def __init__(self, keydir=None, rounds=ROUNDS):
        if not g.AVAILABLE:
            raise ZKError("py_ecc_not_installed")
        self.rounds, self.keydir = rounds, Path(keydir) if keydir else None
        self.pk = self.vk = None
        if self.keydir and (self.keydir / "vk.json").exists():
            self.load()
        else:
            self.pk, self.vk = g.setup(build_circuit(_DUMMY, rounds))
            if self.keydir:
                self.save()

    def save(self):
        self.keydir.mkdir(parents=True, exist_ok=True)
        e = g.pt_enc
        vk = {"alpha1": e(self.vk["alpha1"]), "beta2": e(self.vk["beta2"]), "gamma2": e(self.vk["gamma2"]),
              "delta2": e(self.vk["delta2"]), "IC": [e(p) for p in self.vk["IC"]], "rounds": self.rounds}
        pk = {k: e(self.pk[k]) for k in ("alpha1", "beta1", "beta2", "delta1", "delta2")}
        pk.update(A=[e(p) for p in self.pk["A"]], B1=[e(p) for p in self.pk["B1"]], B2=[e(p) for p in self.pk["B2"]],
                  L={str(j): e(p) for j, p in self.pk["L"].items()}, H=[e(p) for p in self.pk["H"]],
                  m=self.pk["m"], n_pub=self.pk["n_pub"], nvars=self.pk["nvars"])
        (self.keydir / "vk.json").write_text(json.dumps(vk))
        fd = os.open(self.keydir / "pk.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(pk, f)

    def load(self):
        d, vk = g.pt_dec, json.loads((self.keydir / "vk.json").read_text())
        if vk["rounds"] != self.rounds:
            raise ZKError("rounds_mismatch")
        self.vk = {k: d(vk[k]) for k in ("alpha1", "beta2", "gamma2", "delta2")}
        self.vk["IC"] = [d(p) for p in vk["IC"]]
        p = self.keydir / "pk.json"
        if p.exists():
            pk = json.loads(p.read_text())
            self.pk = {k: d(pk[k]) for k in ("alpha1", "beta1", "beta2", "delta1", "delta2")}
            self.pk.update(A=[d(x) for x in pk["A"]], B1=[d(x) for x in pk["B1"]], B2=[d(x) for x in pk["B2"]],
                           L={int(j): d(x) for j, x in pk["L"].items()}, H=[d(x) for x in pk["H"]],
                           m=pk["m"], n_pub=pk["n_pub"], nvars=pk["nvars"])

    def enroll(self, principal_secret_hex, mask, session_config, env_tokens):
        """Issuer/holder side: returns the public commitment (hex) to register for this credential."""
        return format(commit(secret_scalar(principal_secret_hex), mask,
                             session_salt(session_config, env_tokens), self.rounds), "x")

    def prove(self, principal_secret_hex, mask, session_config, env_tokens, tool_names, tool, tenant, agent, nonce):
        if self.pk is None:
            raise ZKError("no_proving_key")
        sec, salt = secret_scalar(principal_secret_hex), session_salt(session_config, env_tokens)
        M = tool_selector(tool_names, tool)
        if not mask & M:
            raise ZKError("tool_not_permitted")
        w = dict(C=commit(sec, mask, salt, self.rounds), M=M, chal=challenge_scalar(nonce, tenant, agent, tool),
                 secret=sec, mask=mask, salt=salt)
        pr = g.prove(self.pk, build_circuit(w, self.rounds))
        return {"A": g.pt_enc(pr["A"]), "B": g.pt_enc(pr["B"]), "C": g.pt_enc(pr["C"])}

    def verify(self, commitment_hex, tool_names, tool, tenant, agent, nonce, proof):
        try:
            pub = [int(commitment_hex, 16), tool_selector(tool_names, tool),
                   challenge_scalar(nonce, tenant, agent, tool)]
            pr = {"A": g.pt_dec(proof["A"]), "B": g.pt_dec(proof["B"]), "C": g.pt_dec(proof["C"])}
            return g.verify(self.vk, pub, pr)
        except (ZKError, KeyError, ValueError, TypeError, IndexError, AssertionError):
            return False


class Verifier:
    """Server-side: issues single-use nonces (TTL) and verifies assertions against registered commitments."""

    def __init__(self, zk, ttl_s=60):
        self.zk, self.ttl, self._nonces, self._commit = zk, ttl_s, {}, {}

    def register(self, tenant, agent, commitment_hex):
        self._commit[(tenant, agent)] = commitment_hex

    def challenge(self):
        now = time.time()
        self._nonces = {n: t for n, t in self._nonces.items() if t > now}
        n = secrets.token_hex(16)
        self._nonces[n] = now + self.ttl
        return n

    def assert_identity(self, tenant, agent, tool, tool_names, nonce, proof):
        exp = self._nonces.pop(nonce, None)                  # single use, consumed even on failure
        c = self._commit.get((tenant, agent))
        if exp is None or exp < time.time() or c is None:
            return False
        return self.zk.verify(c, tool_names, tool, tenant, agent, nonce.encode(), proof)
