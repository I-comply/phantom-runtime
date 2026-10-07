"""Ingestion rules for money events: positive amounts, no overdrafts, and staking that moves funds."""
import pytest
from .conftest import mint_key, eid


def _post(client, key, entity, etype, payload):
    return client.post("/api/events/", json={"entity_id": entity, "event_type": etype, "payload": payload},
                       headers={"X-API-Key": key})


def _state(client, key, entity):
    r = client.get(f"/api/state/{entity}", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    return r.json()["state"]


@pytest.fixture
def key(client, admin_key, workspace):
    return mint_key(client, admin_key, workspace["id"])


@pytest.mark.parametrize("amount", ["0", "-5", "-0.01"])
@pytest.mark.parametrize("etype", ["deposit", "withdraw", "transfer", "claim_rewards", "lock_stake", "release_stake"])
def test_non_positive_amount_rejected(client, key, etype, amount):
    assert _post(client, key, eid(), etype, {"asset": "USD", "amount": amount}).status_code == 422


def test_missing_amount_rejected(client, key):
    assert _post(client, key, eid(), "deposit", {"asset": "USD"}).status_code == 422


def test_overdraft_rejected_and_leaves_state_untouched(client, key):
    e = eid()
    assert _post(client, key, e, "deposit", {"asset": "USD", "amount": "10"}).status_code == 200
    assert _post(client, key, e, "withdraw", {"asset": "USD", "amount": "10.01"}).status_code == 422
    assert _post(client, key, e, "transfer", {"asset": "USD", "amount": "11"}).status_code == 422
    assert _post(client, key, e, "withdraw", {"asset": "EUR", "amount": "1"}).status_code == 422
    assert _post(client, key, e, "withdraw", {"asset": "USD", "amount": "10"}).status_code == 200
    assert _state(client, key, e)["balances"]["USD"] == "0"


def test_trade_checks_from_asset_balance(client, key):
    e = eid()
    _post(client, key, e, "deposit", {"asset": "USD", "amount": "100"})
    bad = _post(client, key, e, "trade", {"from_asset": "USD", "from_amount": "101", "to_asset": "BTC", "to_amount": "1"})
    assert bad.status_code == 422
    ok = _post(client, key, e, "trade", {"from_asset": "USD", "from_amount": "100", "to_asset": "BTC", "to_amount": "2"})
    assert ok.status_code == 200
    assert _state(client, key, e)["balances"] == {"USD": "0", "BTC": "2"}


def test_staking_moves_funds_between_available_and_staked(client, key):
    e = eid()
    _post(client, key, e, "deposit", {"asset": "ETH", "amount": "10"})
    assert _post(client, key, e, "lock_stake", {"asset": "ETH", "amount": "4"}).status_code == 200
    s = _state(client, key, e)
    assert s["balances"]["ETH"] == "6" and s["staked"]["ETH"] == "4"
    assert _post(client, key, e, "lock_stake", {"asset": "ETH", "amount": "7"}).status_code == 422  # only 6 available
    assert _post(client, key, e, "withdraw", {"asset": "ETH", "amount": "7"}).status_code == 422    # staked funds are locked
    assert _post(client, key, e, "release_stake", {"asset": "ETH", "amount": "5"}).status_code == 422
    assert _post(client, key, e, "release_stake", {"asset": "ETH", "amount": "4"}).status_code == 200
    s = _state(client, key, e)
    assert s["balances"]["ETH"] == "10" and s["staked"]["ETH"] == "0"


def test_legacy_stake_events_keep_their_meaning(client, key):
    """'stake'/'unstake' never moved balances; they must replay exactly as before."""
    e = eid()
    _post(client, key, e, "deposit", {"asset": "ETH", "amount": "10"})
    assert _post(client, key, e, "stake", {"asset": "ETH", "amount": "3"}).status_code == 200
    assert _state(client, key, e)["balances"]["ETH"] == "10"


def test_overdraft_allowed_by_config(client, key, monkeypatch):
    monkeypatch.setenv("PHANTOM_ALLOW_OVERDRAFT", "1")
    e = eid()
    assert _post(client, key, e, "withdraw", {"asset": "USD", "amount": "5"}).status_code == 200
    assert _state(client, key, e)["balances"]["USD"] == "-5"


def test_defi_route_applies_same_rules(client, key):
    e = eid()
    hdr = {"X-API-Key": key}
    body = lambda t, a: {"entity_id": e, "event_type": t, "asset": "USD", "amount": a}
    assert client.post("/api/defi/events", json=body("withdraw", "1"), headers=hdr).status_code == 400
    assert client.post("/api/defi/events", json=body("deposit", "-1"), headers=hdr).status_code == 400
    assert client.post("/api/defi/events", json=body("deposit", "5"), headers=hdr).status_code in (200, 201)
    assert client.post("/api/defi/events", json=body("lock_stake", "2"), headers=hdr).status_code in (200, 201)
    p = client.get(f"/api/defi/portfolio/{e}", headers=hdr).json()
    assert p["balances"]["USD"] == "3" and p["staked"]["USD"] == "2"
