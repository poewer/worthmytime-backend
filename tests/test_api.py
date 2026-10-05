import pytest
from sanic_testing.reusable import ReusableClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    with ReusableClient(app) as c:
        yield c


PROFILE = {"monthly_income": 7000}


def test_anonymous_calculate(client):
    _, res = client.post(
        "/api/v1/calculate",
        json={"profile": PROFILE, "calculation": {"name": "iPhone", "purchase_price": 5299}},
    )
    assert res.status == 200
    assert round(res.json["work"]["hours"]) == 127


def test_validation_error(client):
    _, res = client.post("/api/v1/calculate", json={"profile": PROFILE, "calculation": {"purchase_price": -1}})
    assert res.status == 422


def test_full_flow(client):
    _, res = client.post("/api/v1/auth/register", json={"email": "a@b.pl", "password": "supersecret1"})
    assert res.status == 201
    auth = {"Authorization": f"Bearer {res.json['token']}"}

    _, res = client.post("/api/v1/calculations", json={"name": "x", "purchase_price": 100}, headers=auth)
    assert res.status == 409  # brak profilu

    _, res = client.put("/api/v1/profile", json=PROFILE, headers=auth)
    assert res.json["effective_hourly_rate"] == 41.67

    _, res = client.post("/api/v1/calculations", json={"name": "iPhone", "purchase_price": 5299}, headers=auth)
    assert res.status == 201
    cid = res.json["id"]

    _, res = client.post(f"/api/v1/calculations/{cid}/share", headers=auth)
    pid = res.json["public_id"]
    _, res = client.get(f"/api/v1/shared/{pid}")
    assert res.status == 200
    assert "hourly_rate" not in res.json["result"]
    assert "id" not in res.json

    _, res = client.post(f"/api/v1/calculations/{cid}/duplicate", headers=auth)
    assert res.json["name"] == "iPhone (kopia)"

    _, res = client.post("/api/v1/compare", json={"a_id": cid, "b": {"name": "old", "purchase_price": 0}}, headers=auth)
    assert res.json["difference"]["hours"] > 100

    _, res = client.get("/api/v1/dashboard", headers=auth)
    assert res.json["count"] == 2

    _, res = client.delete(f"/api/v1/calculations/{cid}", headers=auth)
    assert res.status == 200
    _, res = client.get(f"/api/v1/shared/{pid}")
    assert res.status == 404


def test_other_user_cannot_read(client):
    _, r1 = client.post("/api/v1/auth/register", json={"email": "u1@b.pl", "password": "supersecret1"})
    _, r2 = client.post("/api/v1/auth/register", json={"email": "u2@b.pl", "password": "supersecret1"})
    h1 = {"Authorization": f"Bearer {r1.json['token']}"}
    h2 = {"Authorization": f"Bearer {r2.json['token']}"}
    client.put("/api/v1/profile", json=PROFILE, headers=h1)
    _, c = client.post("/api/v1/calculations", json={"name": "x", "purchase_price": 1}, headers=h1)
    _, res = client.get(f"/api/v1/calculations/{c.json['id']}", headers=h2)
    assert res.status == 404
