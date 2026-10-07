# ruff: noqa: F811
from tests.test_api import PROFILE, _register, client  # noqa: F401

URL = "/api/v1/expenses/import"


def _item(key="2026-10-06|-5.50|P425125001349343126458731", **over):
    return {"category": "FUN", "amount": 5.5, "note": "ZABKA", "spent_on": "2026-10-06", "key": key, **over}


def test_import_creates_entries_with_import_source(client):
    auth = _register(client, "imp1@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    items = [_item(), _item(key="2026-10-06|-24.68|P425125001349343125114308", amount=24.68, note="ZABKA")]
    _, res = client.post(URL, json={"items": items}, headers=auth)
    assert res.status == 201 and res.json == {"created": 2, "skipped": 0}

    _, listed = client.get("/api/v1/expenses?month=2026-10", headers=auth)
    assert {e["source_type"] for e in listed.json["items"]} == {"IMPORT"}
    assert listed.json["totals"]["FUN"] == 30.18  # wydatki z importu liczą się do wydanych w kategorii


def test_import_is_idempotent_and_skips_duplicates_within_request(client):
    auth = _register(client, "imp2@b.pl")
    items = [_item(), _item(), _item(key="2026-10-07|-25.00|BLIK00000095117031783", amount=25, note="PLAYER.PL")]
    _, first = client.post(URL, json={"items": items}, headers=auth)
    assert first.json == {"created": 2, "skipped": 1}  # powtórzony klucz w jednym żądaniu
    _, again = client.post(URL, json={"items": items}, headers=auth)
    assert again.status == 200 and again.json == {"created": 0, "skipped": 3}  # ponowny import tego samego wyciągu
    _, listed = client.get("/api/v1/expenses?month=2026-10", headers=auth)
    assert len(listed.json["items"]) == 2


def test_same_key_for_different_users_does_not_collide(client):
    a, b = _register(client, "imp3@b.pl"), _register(client, "imp4@b.pl")
    assert client.post(URL, json={"items": [_item()]}, headers=a)[1].json["created"] == 1
    assert client.post(URL, json={"items": [_item()]}, headers=b)[1].json["created"] == 1
    assert len(client.get("/api/v1/expenses?month=2026-10", headers=b)[1].json["items"]) == 1


def test_import_validation_and_auth(client):
    auth = _register(client, "imp5@b.pl")
    assert client.post(URL, json={"items": [_item()]})[1].status == 401
    for bad in (
        {"items": []},
        {"items": [_item(amount=0)]},
        {"items": [_item(category="X")]},
        {"items": [_item(key="krotki")]},
        {"items": [_item(spent_on="nie-data")]},
        {"items": [_item(key=f"klucz-{i:04d}") for i in range(501)]},
    ):
        assert client.post(URL, json=bad, headers=auth)[1].status == 422
    big = {"items": [_item(key=f"klucz-{i:04d}") for i in range(500)]}
    assert client.post(URL, json=big, headers=auth)[1].json["created"] == 500


def test_imported_entry_can_be_deleted_and_reimported(client):
    auth = _register(client, "imp6@b.pl")
    client.post(URL, json={"items": [_item()]}, headers=auth)
    eid = client.get("/api/v1/expenses?month=2026-10", headers=auth)[1].json["items"][0]["id"]
    assert client.delete(f"/api/v1/expenses/{eid}", headers=auth)[1].status == 200
    _, res = client.post(URL, json={"items": [_item()]}, headers=auth)
    assert res.json["created"] == 1  # po usunięciu wpisu ten sam wiersz wyciągu można zaimportować ponownie
