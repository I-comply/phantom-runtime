"""Exact decimal amounts for the event reconstructor and for ingestion.

Balances used to be floats (0.1 ten times summed to 0.9999999999999999). They are now Decimal
internally and canonical decimal STRINGS in state and snapshots ("100", "70.5"), so replay is exact
and identical on every machine.

Ingestion is strict (`parse_amount`: int or decimal string, finite, bounded; floats rejected).
Replay is lenient (`lenient`): events written before this change, or by other writers, may hold
floats or junk, and one bad event must not make an entity unreadable forever."""
import re
from decimal import Context, Decimal, InvalidOperation

CTX = Context(prec=60)
MAX_ABS = Decimal("1e30")
_DECIMAL_RE = re.compile(r"^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$")


class AmountError(ValueError):
    pass


def parse_amount(raw, *, allow_float: bool = False) -> Decimal:
    """Strict parse for ingestion. Accepts int and decimal strings; bool, None, NaN/Infinity,
    digit separators and anything over 1e30 are rejected. Floats only with allow_float (replay of
    legacy events), converted through repr so 0.1 means exactly 0.1."""
    if isinstance(raw, bool) or raw is None:
        raise AmountError("amount must be a decimal string or an integer")
    if isinstance(raw, int):
        d = Decimal(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not _DECIMAL_RE.match(s):
            raise AmountError(f"not a decimal number: {raw[:40]!r}")
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise AmountError(f"not a decimal number: {raw[:40]!r}")
    elif isinstance(raw, float) and allow_float:
        d = Decimal(repr(raw))
    elif isinstance(raw, float):
        raise AmountError("send amounts as decimal strings (e.g. \"0.1\"), not JSON numbers with a fraction")
    else:
        raise AmountError("amount must be a decimal string or an integer")
    if not d.is_finite():
        raise AmountError("amount must be finite")
    if abs(d) > MAX_ABS:
        raise AmountError("amount out of range")
    return d


def lenient(raw) -> Decimal:
    """Replay-side parse: legacy floats are read exactly through repr, anything unusable is 0."""
    try:
        return parse_amount(raw, allow_float=True)
    except AmountError:
        return Decimal(0)


def usable(raw) -> bool:
    try:
        parse_amount(raw, allow_float=True)
        return True
    except AmountError:
        return False


def fmt(d: Decimal) -> str:
    """Canonical string: no exponent, no trailing zeros, no negative zero."""
    s = format(d.normalize(CTX), "f")
    return "0" if s in ("-0", "") else s


def add(a: Decimal, b: Decimal) -> Decimal:
    return CTX.add(a, b)


def sub(a: Decimal, b: Decimal) -> Decimal:
    return CTX.subtract(a, b)


MONEY_FIELDS = ("amount", "from_amount", "to_amount", "price")
MONEY_EVENT_TYPES = frozenset({"deposit", "withdraw", "trade", "transfer", "stake", "unstake", "claim_rewards",
                               "lock_stake", "release_stake"})
# The legacy 'stake'/'unstake' events never moved balances and keep that meaning (and their old, lax
# ingestion). lock_stake/release_stake move funds between balances and `staked`.
RULE_CHECKED = MONEY_EVENT_TYPES - {"stake", "unstake"}
OVERDRAFT_ENV = "PHANTOM_ALLOW_OVERDRAFT"


def validate_money_payload(event_type: str, payload: dict) -> None:
    """Ingestion check for money-bearing event types: every money field present must parse strictly."""
    if event_type not in MONEY_EVENT_TYPES:
        return
    for k in MONEY_FIELDS:
        if k in payload and payload[k] is not None:
            try:
                parse_amount(payload[k])
            except AmountError as e:
                raise AmountError(f"{k}: {e}")


def _positive(payload: dict, field: str, *, required: bool) -> Decimal:
    if field not in payload or payload[field] is None:
        if required:
            raise AmountError(f"{field} is required")
        return Decimal(0)
    d = parse_amount(payload[field])
    if d <= 0:
        raise AmountError(f"{field} must be greater than zero")
    return d


def check_applicable(event_type: str, payload: dict, state: dict) -> None:
    """Ingestion rules, evaluated against the entity's current state while its lock is held:
    amounts are positive, and nothing can be spent, traded, transferred or staked beyond the available
    balance (or released beyond what is staked). Set PHANTOM_ALLOW_OVERDRAFT=1 to allow overdrafts.
    Replay never calls this, so events written before these rules still replay."""
    if event_type not in RULE_CHECKED:
        return
    import os
    allow_overdraft = os.getenv(OVERDRAFT_ENV, "").lower() in ("1", "true", "yes")
    balances = state.get("balances") if isinstance(state.get("balances"), dict) else {}
    staked = state.get("staked") if isinstance(state.get("staked"), dict) else {}
    asset = payload.get("asset", "USD")

    def need(source: dict, key, amount: Decimal, what: str):
        if not allow_overdraft and lenient(source.get(key, 0)) < amount:
            raise AmountError(f"insufficient {what} {key}")

    if event_type == "trade":
        from_amount = _positive(payload, "from_amount", required=False)
        _positive(payload, "to_amount", required=False)
        if payload.get("from_asset") and from_amount:
            need(balances, payload["from_asset"], from_amount, "balance")
        return
    amount = _positive(payload, "amount", required=True)
    if event_type in ("withdraw", "transfer", "lock_stake"):
        need(balances, asset, amount, "balance")
    elif event_type == "release_stake":
        need(staked, asset, amount, "staked")
