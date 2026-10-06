# ruff: noqa: F811
from tests.test_api import PROFILE, _register, client  # noqa: F401  (fixture client)

PASSWORD = "supersecret1"


def _seed(client, auth):
    """Dane w kaĹĽdej tabeli uĹĽytkownika: obliczenie z linkiem, budĹĽet, kredyt, wydatek, ĹĽyczenie, cel."""
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    _, res = client.post("/api/v1/calculations", json={"name": "Rower", "purchase_price": 3000}, headers=auth)
    cid = res.json["id"]
    _, res = client.post(f"/api/v1/calculations/{cid}/share", headers=auth)
    budget = {"percentages": {"NEEDS": 50, "FUTURE": 20, "GOALS": 10, "FUN": 20}}
    client.put("/api/v1/budget", json=budget, headers=auth)
    client.post("/api/v1/expenses", json={"category": "FUN", "amount": 50, "note": "kawa"}, headers=auth)
    client.post("/api/v1/wishlist", json={"name": "Monitor", "price": 900, "cooldown_days": 7}, headers=auth)
    client.post("/api/v1/goals", json={"name": "Wakacje", "target_amount": 5000}, headers=auth)
    return res.json["public_id"]


def test_change_password(client):
    auth = _register(client, "pw@b.pl")
    url = "/api/v1/auth/change-password"

    def change(current, new, headers=auth):
        return client.post(url, json={"current_password": current, "new_password": new}, headers=headers)[1]

    assert change("zle-haslo-1", "nowehaslo123").status == 403
    assert change(PASSWORD, PASSWORD).status == 422
    assert change(PASSWORD, "krotkie").status == 422
    assert change(PASSWORD, "nowehaslo123", headers={}).status == 401

    _, res = client.post(url, json={"current_password": PASSWORD, "new_password": "nowehaslo123"}, headers=auth)
    assert res.status == 200 and res.json["token"]
    assert client.post("/api/v1/auth/login", json={"email": "pw@b.pl", "password": PASSWORD})[1].status == 401
    assert client.post("/api/v1/auth/login", json={"email": "pw@b.pl", "password": "nowehaslo123"})[1].status == 200


def test_delete_account_removes_everything_including_public_link(client):
    auth = _register(client, "del@b.pl")
    other = _register(client, "other@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=other)
    client.post("/api/v1/expenses", json={"category": "FUN", "amount": 10}, headers=other)
    pid = _seed(client, auth)
    assert client.get(f"/api/v1/shared/{pid}")[1].status == 200


    def delete(password, headers=auth):
        return client.request("/api/v1/account", http_method="DELETE", json={"password": password}, headers=headers)[1]

    assert delete("zle-haslo-1").status == 403
    assert delete(PASSWORD, headers={}).status == 401
    res = delete(PASSWORD)
    assert res.status == 200 and res.json["deleted"] is True

    assert client.get(f"/api/v1/shared/{pid}")[1].status == 404
    assert client.get("/api/v1/auth/me", headers=auth)[1].status == 401
    assert client.post("/api/v1/auth/login", json={"email": "del@b.pl", "password": PASSWORD})[1].status == 401
    # konto moĹĽna zaĹ‚oĹĽyÄ‡ ponownie, a cudze dane zostajÄ… nietkniÄ™te
    assert client.post("/api/v1/auth/register", json={"email": "del@b.pl", "password": PASSWORD})[1].status == 201
    _, res = client.get("/api/v1/expenses", headers=other)
    assert len(res.json["items"]) == 1


def test_account_export_contains_all_user_data_and_no_password_hash(client):
    auth = _register(client, "exp@b.pl")
    other = _register(client, "exp2@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=other)
    client.post("/api/v1/calculations", json={"name": "Cudze", "purchase_price": 1}, headers=other)
    _seed(client, auth)

    assert client.get("/api/v1/account/export")[1].status == 401
    _, res = client.get("/api/v1/account/export", headers=auth)
    assert res.status == 200
    body = res.json
    assert body["account"]["email"] == "exp@b.pl"
    assert [c["name"] for c in body["calculations"]] == ["Rower"]
    assert body["calculations"][0]["public_id"]
    assert isinstance(body["costs"], list)
    assert body["budget"]["pct_fun"] == 20
    assert [e["note"] for e in body["expenses"]] == ["kawa"]
    assert [w["name"] for w in body["wishlist"]] == ["Monitor"]
    assert [g["name"] for g in body["goals"]] == ["Wakacje"]
    assert body["loans"] == []
    assert "password" not in str(body).lower()


