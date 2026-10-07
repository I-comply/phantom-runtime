"""Minimal Groth16 zk-SNARK over BN254 (R1CS -> QAP). Needs `py_ecc` (pip install py_ecc).

Setup is a single-party trusted setup: whoever runs setup() must discard the toxic waste (it never leaves the
function). For production use a multi-party ceremony / audited prover; this is a self-contained reference.
"""
import secrets

try:
    from py_ecc.optimized_bn128 import (G1, G2, Z1, Z2, FQ, FQ2, add, multiply, neg, normalize, pairing,
                                        curve_order as R, is_on_curve, b, b2)
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False
    R = 21888242871839275222246405745257275088548364400416034343698204186575808495617


class CircuitBuilder:
    """Linear combinations are {var_index: coeff}. Var 0 is the constant one. Public vars must be allocated first."""

    def __init__(self):
        self.vals, self.n_pub, self.cons, self._sealed = [1], 0, [], False

    def pub(self, v):
        if self._sealed:
            raise ValueError("public inputs must be allocated before private ones")
        self.vals.append(v % R); self.n_pub += 1
        return {len(self.vals) - 1: 1}

    def priv(self, v):
        self._sealed = True
        self.vals.append(v % R)
        return {len(self.vals) - 1: 1}

    def val(self, lc):
        return sum(c * self.vals[i] for i, c in lc.items()) % R

    @staticmethod
    def add(*lcs):
        out = {}
        for lc in lcs:
            for i, c in lc.items():
                out[i] = (out.get(i, 0) + c) % R
        return out

    @staticmethod
    def scale(lc, k):
        return {i: (c * k) % R for i, c in lc.items()}

    @staticmethod
    def const(k):
        return {0: k % R}

    def mul(self, a, bb):
        out = self.priv(self.val(a) * self.val(bb))
        self.cons.append((a, bb, out))
        return out

    def assert_eq(self, a, bb):
        self.cons.append((a, {0: 1}, bb))


def _inv(x):
    return pow(x, R - 2, R)


def _lagrange_at(tau, m):
    """L_i(tau) for domain points 1..m."""
    z = 1
    for j in range(1, m + 1):
        z = z * (tau - j) % R
    fact = [1] * (m + 1)
    for i in range(1, m + 1):
        fact[i] = fact[i - 1] * i % R
    out = []
    for i in range(m):                      # point x_i = i+1; prod_{j!=i}(x_i-x_j) = i! * (m-1-i)! * (-1)^(m-1-i)
        w = fact[i] * fact[m - 1 - i] % R
        if (m - 1 - i) & 1:
            w = -w % R
        out.append(z * _inv((tau - (i + 1)) * w % R) % R)
    return z, out


def _qap_at(cons, nvars, L):
    u, v, w = [0] * nvars, [0] * nvars, [0] * nvars
    for i, (a, bb, c) in enumerate(cons):
        for j, k in a.items(): u[j] = (u[j] + k * L[i]) % R
        for j, k in bb.items(): v[j] = (v[j] + k * L[i]) % R
        for j, k in c.items(): w[j] = (w[j] + k * L[i]) % R
    return u, v, w


def _rand():
    while True:
        x = secrets.randbelow(R)
        if x > 1:
            return x


def _g1(k): return multiply(G1, k % R)
def _g2(k): return multiply(G2, k % R)


def setup(cb):
    """-> (pk, vk) for the circuit structure held by builder `cb` (witness values are ignored)."""
    cons, nvars, n_pub, m = cb.cons, len(cb.vals), cb.n_pub, len(cb.cons)
    while True:
        alpha, beta, gamma, delta, tau = (_rand() for _ in range(5))
        z, L = _lagrange_at(tau, m)
        if z != 0:
            break
    u, v, w = _qap_at(cons, nvars, L)
    gi, di = _inv(gamma), _inv(delta)
    comb = [(beta * u[j] + alpha * v[j] + w[j]) % R for j in range(nvars)]
    pk = {
        "alpha1": _g1(alpha), "beta1": _g1(beta), "beta2": _g2(beta), "delta1": _g1(delta), "delta2": _g2(delta),
        "A": [_g1(x) if x else None for x in u],
        "B1": [_g1(x) if x else None for x in v],
        "B2": [_g2(x) if x else None for x in v],
        "L": {j: _g1(comb[j] * di) for j in range(n_pub + 1, nvars)},
        "H": [], "m": m, "n_pub": n_pub, "nvars": nvars,
    }
    t = z * di % R
    for _ in range(m - 1):
        pk["H"].append(_g1(t)); t = t * tau % R
    vk = {"alpha1": pk["alpha1"], "beta2": pk["beta2"], "gamma2": _g2(gamma), "delta2": pk["delta2"],
          "IC": [_g1(comb[j] * gi) for j in range(n_pub + 1)]}
    return pk, vk


def _polymul(a, bb):
    out = [0] * (len(a) + len(bb) - 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(bb):
                out[i + j] = (out[i + j] + x * y) % R
    return out


def _interp(ys, m):
    """Coefficients of the poly of degree < m with p(i+1)=ys[i]."""
    zc = [1]
    for j in range(1, m + 1):
        zc = _polymul(zc, [-j % R, 1])
    out = [0] * m
    for i in range(m):
        if not ys[i]:
            continue
        # q = Z/(x-(i+1)) by synthetic division
        q, carry = [0] * m, 0
        for k in range(m, 0, -1):
            carry = (zc[k] + carry * (i + 1)) % R
            q[k - 1] = carry
        d = 1
        for j in range(m):
            if j != i:
                d = d * (i - j) % R
        s = ys[i] * _inv(d) % R
        for k in range(m):
            out[k] = (out[k] + s * q[k]) % R
    return out


def _msm(points, scalars, zero):
    acc = zero
    for p, s in zip(points, scalars):
        if p is not None and s % R:
            acc = add(acc, multiply(p, s % R))
    return acc


def prove(pk, cb):
    cons, vals, m = cb.cons, cb.vals, pk["m"]
    if len(cons) != m or len(vals) != pk["nvars"]:
        raise ValueError("circuit/proving key mismatch")
    ev = lambda lc: sum(c * vals[i] for i, c in lc.items()) % R
    ya, yb, yc = [ev(a) for a, _, _ in cons], [ev(bb) for _, bb, _ in cons], [ev(c) for _, _, c in cons]
    if any(x * y % R != z for x, y, z in zip(ya, yb, yc)):
        raise ValueError("unsatisfied witness")
    pa, pb, pc = _interp(ya, m), _interp(yb, m), _interp(yc, m)
    num = _polymul(pa, pb)
    for i, c in enumerate(pc):
        num[i] = (num[i] - c) % R
    zc = [1]
    for j in range(1, m + 1):
        zc = _polymul(zc, [-j % R, 1])
    h = [0] * (len(num) - m)                # long division by monic Z (degree m)
    for k in range(len(num) - 1, m - 1, -1):
        q = num[k]
        h[k - m] = q
        if q:
            for j in range(m + 1):
                num[k - m + j] = (num[k - m + j] - q * zc[j]) % R
    if any(num[:m]):
        raise ValueError("QAP not divisible (internal error)")
    h = (h + [0] * (m - 1))[:m - 1]
    r_, s_ = _rand(), _rand()
    A = add(add(pk["alpha1"], _msm(pk["A"], vals, Z1)), multiply(pk["delta1"], r_))
    B2 = add(add(pk["beta2"], _msm(pk["B2"], vals, Z2)), multiply(pk["delta2"], s_))
    B1 = add(add(pk["beta1"], _msm(pk["B1"], vals, Z1)), multiply(pk["delta1"], s_))
    n_pub = pk["n_pub"]
    C = add(_msm([pk["L"][j] for j in range(n_pub + 1, len(vals))], vals[n_pub + 1:], Z1), _msm(pk["H"], h, Z1))
    C = add(C, add(multiply(A, s_), multiply(B1, r_)))
    C = add(C, neg(multiply(pk["delta1"], r_ * s_ % R)))
    return {"A": A, "B": B2, "C": C}


def verify(vk, public, proof):
    if len(public) + 1 != len(vk["IC"]):
        return False
    A, B, C = proof["A"], proof["B"], proof["C"]
    if not (is_on_curve(A, b) and is_on_curve(C, b) and is_on_curve(B, b2)):
        return False
    if any(not 0 <= x < R for x in public):
        return False
    acc = vk["IC"][0]
    for x, p in zip(public, vk["IC"][1:]):
        acc = add(acc, multiply(p, x))
    lhs = pairing(B, A)
    rhs = (pairing(vk["beta2"], vk["alpha1"]) * pairing(vk["gamma2"], acc) * pairing(vk["delta2"], C))
    return lhs == rhs


# ---- (de)serialization: points <-> hex strings ----

def pt_enc(p):
    if p is None:
        return None
    x, y = normalize(p)
    if isinstance(x, FQ):
        return [format(x.n, "x"), format(y.n, "x")]
    return [[format(int(c), "x") for c in x.coeffs], [format(int(c), "x") for c in y.coeffs]]


def pt_dec(o):
    if o is None:
        return None
    if isinstance(o[0], str):
        return (FQ(int(o[0], 16)), FQ(int(o[1], 16)), FQ.one())
    return (FQ2([int(c, 16) for c in o[0]]), FQ2([int(c, 16) for c in o[1]]), FQ2.one())
