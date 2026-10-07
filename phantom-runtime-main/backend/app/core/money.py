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
MONEY_EVENT_TYPES = frozenset({"deposit", "withdraw", "trade", "transfer", "stake", "unstake", "claim_rewards"})


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
