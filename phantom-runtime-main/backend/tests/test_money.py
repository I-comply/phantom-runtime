"""Money is exact: Decimal arithmetic in replay and in the portfolio, canonical decimal strings in
state and snapshots, strict ingestion (no floats), lenient replay (one bad event can't brick an entity)."""
import copy

import pytest

from app.core import money
from app.core.models import Event
from app.core.reconstructor_v2 import StateReconstructorV2
from .conftest import mint_key, eid


def replay(*events):
    return StateReconstructorV2.reconstruct([Event(entity_id="x", event_type=t, payload=copy.deepcopy(p)) for t, p in events])


def test_ten_deposits_of_a_tenth_are_exactly_one():
    state = replay(*[("deposit", {"asset": "USD", "amount": "0.1"})] * 10)
    assert state["balances"]["USD"] == "1"        # floats gave 0.9999999999999999


def test_classic_float_cases_are_exact_and_canonical():
    state = replay(("deposit", {"asset": "USD", "amount": "0.1"}), ("deposit", {"asset": "USD", "amount": "0.2"}))
    assert state["balances"]["USD"] == "0.3"
    state = replay(("deposit", {"asset": "BTC", "amount": "1.10"}), ("withdraw", {"asset": "BTC", "amount": "1.10"}))
    assert state["balances"]["BTC"] == "0"        # no "-0", no "0E-2"


def test_trade_transfer_and_claim_rewards():
    state = replay(
        ("deposit", {"asset": "USD", "amount": "100"}),
        ("trade", {"from_asset": "USD", "to_asset": "BTC", "from_amount": "10.5", "to_amount": "0.00021"}),
        ("transfer", {"asset": "BTC", "amount": "0.00001"}),
        ("claim_rewards", {"asset": "BTC", "amount": "0.5"}),
    )
    assert state["balances"] == {"USD": "89.5", "BTC": "0.5002"}


def test_history_carries_canonical_amounts_and_payload_extras():
    state = replay(("deposit", {"asset": "USD", "amount": 100, "memo": "x", "type": "spoof"}))
    assert state["event_history"] == [{"type": "deposit", "asset": "USD", "amount": "100", "memo": "x"}]


def test_legacy_float_events_and_float_balances_replay_exactly():
    # events and snapshots written before this change hold JSON floats
    state = replay(("deposit", {"asset": "USD", "amount": 0.1}), ("deposit", {"asset": "USD", "amount": 0.2}))
    assert state["balances"]["USD"] == "0.3"
    legacy = {"balances": {"USD": 70.0}, "event_history": []}
    StateReconstructorV2.apply_event(legacy, Event(entity_id="x", event_type="deposit", payload={"asset": "USD", "amount": "0.5"}))
    assert legacy["balances"]["USD"] == "70.5"


@pytest.mark.parametrize("bad", ["abc", "", "NaN", "Infinity", "1_000", None, True, [1], {"a": 1}, "1e999"])
def test_a_bad_amount_in_the_log_does_not_break_replay(bad):
    state = replay(("deposit", {"asset": "USD", "amount": "5"}), ("deposit", {"asset": "USD", "amount": bad}),
                   ("deposit", {"asset": "USD", "amount": "1"}))
    assert state["balances"]["USD"] == "6"
    assert state["event_history"][1].get("invalid_amount") is True


def test_replay_is_deterministic():
    evs = [("deposit", {"asset": "USD", "amount": "0.1"})] * 7 + [("withdraw", {"asset": "USD", "amount": "0.3"})]
    assert replay(*evs) == replay(*evs)


@pytest.mark.parametrize("raw,ok", [("0", True), ("-1.5", True), (" 2 ", True), ("1e3", True), (".5", True), (7, True),
                                    (0.1, False), (True, False), ("1_0", False), ("0x10", False), ("١٢", False), ("1e31", False),
                                    ("", False), (float("nan"), False)])
def test_parse_amount_is_strict(raw, ok):
    if ok:
        money.parse_amount(raw)
    else:
        with pytest.raises(money.AmountError):
            money.parse_amount(raw)


def test_fmt_is_canonical():
    from decimal import Decimal
    assert [money.fmt(Decimal(x)) for x in ("100.00", "1E+2", "-0", "0.50", "-0.0010")] == ["100", "100", "0", "0.5", "-0.001"]


# ---- ingestion over HTTP ----

def _key(client, workspace):
    return mint_key(client, None, workspace["id"])


@pytest.mark.parametrize("amount,status", [("0.1", 200), (100, 200), (0.1, 422), ("abc", 422), (True, 422), ("1e999", 422)])
def test_v1_money_events_reject_floats_and_junk(client, workspace, amount, status):
    r = client.post("/api/events/", json={"entity_id": eid(), "event_type": "deposit", "payload": {"asset": "USD", "amount": amount}},
                    headers={"X-API-Key": _key(client, workspace)})
    assert r.status_code == status, r.text


def test_v1_non_money_events_may_carry_numbers(client, workspace):
    r = client.post("/api/events/", json={"entity_id": eid(), "event_type": "update", "payload": {"amount": 0.1, "score": 1.5}},
                    headers={"X-API-Key": _key(client, workspace)})
    assert r.status_code == 200


def test_defi_route_validates_amounts_and_metadata_cannot_override_them(client, workspace):
    key, entity = _key(client, workspace), eid()
    h = {"X-API-Key": key}
    bad = client.post("/api/defi/events", json={"entity_id": entity, "event_type": "deposit", "asset": "USD", "amount": "oops"}, headers=h)
    assert bad.status_code == 400
    bad_meta = client.post("/api/defi/events", json={"entity_id": entity, "event_type": "trade", "asset": "USD", "amount": "1",
                                                      "metadata": {"from_asset": "USD", "from_amount": 0.1}}, headers=h)
    assert bad_meta.status_code == 400
    ok = client.post("/api/defi/events", json={"entity_id": entity, "event_type": "deposit", "asset": "USD", "amount": "100.50",
                                                "metadata": {"amount": "999999", "note": "n"}}, headers=h)
    assert ok.status_code == 200, ok.text
    state = client.get(f"/api/state/{entity}", headers=h).json()
    assert state["schema_version"] == 2
    assert state["state"]["balances"] == {"USD": "100.5"}   # metadata did not win


def test_portfolio_is_exact_and_returns_strings(client, workspace):
    key, entity = _key(client, workspace), eid()
    h = {"X-API-Key": key}
    for _ in range(10):
        assert client.post("/api/defi/events", json={"entity_id": entity, "event_type": "deposit", "asset": "USD", "amount": "0.1"}, headers=h).status_code == 200
    p = client.get(f"/api/defi/portfolio/{entity}", headers=h).json()
    assert p["balances"] == {"USD": "1"}
    assert p["recent_transactions"][0]["amount"] == "0.1"
