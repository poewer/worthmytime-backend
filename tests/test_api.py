import asyncio
import os
import random
import socket

import pytest
from sanic_testing.reusable import ReusableClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import create_app
from app.models import Base

# Gdy ustawione (np. w CI): testy API idą na prawdziwym PostgreSQL zamiast SQLite.
# UWAGA: schemat w tej bazie jest przed każdym testem kasowany (drop_all) - używaj tylko bazy testowej.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _free_port() -> int:
    """Wolny port spoza zakresu ephemeral (na Windows jego część jest zarezerwowana - błąd 10013)."""
    for _ in range(50):
        port = random.randint(30000, 39999)
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Brak wolnego portu do testów")


async def _reset_schema(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def client(tmp_path):
    url = TEST_DATABASE_URL or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    if TEST_DATABASE_URL:
        asyncio.run(_reset_schema(url))
    app = create_app(url, create_schema=True)
    with ReusableClient(app, port=_free_port()) as c:
        yield c


PROFILE = {"monthly_income": 7000}


def test_anonymous_calculate(client):
    _, res = client.post(
        "/api/v1/calculate",
        json={"profile": PROFILE, "calculation": {"name": "iPhone", "purchase_price": 5299}},
    )
    assert res.status == 200
    assert round(res.json["work"]["hours"]) == 131


def test_cors_preflight(client):
    _, res = client.options(
        "/api/v1/calculate",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert res.status == 204
    assert res.headers["access-control-allow-origin"] == "*"
    assert "POST" in res.headers["access-control-allow-methods"]


def test_validation_error(client):
    _, res = client.post("/api/v1/calculate", json={"profile": PROFILE, "calculation": {"purchase_price": -1}})
    assert res.status == 422
    assert res.json["errors"][0]["field"] == "calculation.purchase_price"
    assert res.json["errors"][0]["message"]


def test_full_flow(client):
    _, res = client.post("/api/v1/auth/register", json={"email": "a@b.pl", "password": "supersecret1"})
    assert res.status == 201
    auth = {"Authorization": f"Bearer {res.json['token']}"}

    _, res = client.post("/api/v1/calculations", json={"name": "x", "purchase_price": 100}, headers=auth)
    assert res.status == 409  # brak profilu

    _, res = client.put("/api/v1/profile", json=PROFILE, headers=auth)
    assert res.json["effective_hourly_rate"] == 40.38

    _, res = client.post("/api/v1/calculations", json={"name": "iPhone", "purchase_price": 5299}, headers=auth)
    assert res.status == 201
    cid = res.json["id"]

    _, res = client.post(f"/api/v1/calculations/{cid}/share", headers=auth)
    pid = res.json["public_id"]
    _, res = client.get(f"/api/v1/shared/{pid}")
    assert res.status == 200
    assert "hourly_rate" not in res.json["result"]
    assert "income_percent" not in res.json["result"]["work"]
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


def test_budget_warning_for_anonymous_calculation(client):
    body = {
        "profile": {"monthly_income": 10000},
        "budget": {"percentages": {"NEEDS": 50, "FUTURE": 25, "GOALS": 15, "FUN": 10}, "spent": {"FUN": 400}},
        "calculation": {"name": "PlayStation", "purchase_price": 2500, "category": "FUN"},
    }
    _, res = client.post("/api/v1/calculate", json=body)
    b = res.json["budget"]
    assert b["category_budget"] == 1000 and b["available"] == 600
    assert b["fits_budget"] is False
    assert {w["code"] for w in b["warnings"]} >= {"CATEGORY_BUDGET_EXCEEDED", "HIGHER_PRIORITY_AT_RISK"}


def test_no_category_means_no_budget_block(client):
    _, res = client.post(
        "/api/v1/calculate", json={"profile": PROFILE, "calculation": {"name": "x", "purchase_price": 100}}
    )
    assert "budget" not in res.json


def test_budget_endpoints_and_saved_calculation_analysis(client):
    _, res = client.post("/api/v1/auth/register", json={"email": "bud@b.pl", "password": "supersecret1"})
    auth = {"Authorization": f"Bearer {res.json['token']}"}
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)

    _, res = client.get("/api/v1/budget", headers=auth)
    assert res.json["is_custom"] is False
    assert res.json["amounts"]["FUN"] == 1000

    bad = {"percentages": {"NEEDS": 60, "FUTURE": 25, "GOALS": 15, "FUN": 10}}
    _, res = client.put("/api/v1/budget", json=bad, headers=auth)
    assert res.status == 422

    good = {"percentages": {"NEEDS": 40, "FUTURE": 25, "GOALS": 15, "FUN": 20}, "spent": {"FUN": 1500}}
    _, res = client.put("/api/v1/budget", json=good, headers=auth)
    assert res.json["amounts"]["FUN"] == 2000 and res.json["is_custom"] is True

    _, res = client.post(
        "/api/v1/calculations",
        json={"name": "Konsola", "purchase_price": 800, "category": "FUN"},
        headers=auth,
    )
    assert res.status == 201
    assert res.json["input"]["category"] == "FUN"
    assert res.json["result"]["budget"]["available"] == 500
    assert res.json["result"]["budget"]["fits_budget"] is False  # 1500 + 800 > 2000

    # zmiana budżetu od razu zmienia ocenę zapisanego obliczenia
    client.put("/api/v1/budget", json={**good, "spent": {"FUN": 0}}, headers=auth)
    _, res = client.get(f"/api/v1/calculations/{res.json['id']}", headers=auth)
    assert res.json["result"]["budget"]["fits_budget"] is True


def test_other_user_cannot_read(client):
    _, r1 = client.post("/api/v1/auth/register", json={"email": "u1@b.pl", "password": "supersecret1"})
    _, r2 = client.post("/api/v1/auth/register", json={"email": "u2@b.pl", "password": "supersecret1"})
    h1 = {"Authorization": f"Bearer {r1.json['token']}"}
    h2 = {"Authorization": f"Bearer {r2.json['token']}"}
    client.put("/api/v1/profile", json=PROFILE, headers=h1)
    _, c = client.post("/api/v1/calculations", json={"name": "x", "purchase_price": 1}, headers=h1)
    _, res = client.get(f"/api/v1/calculations/{c.json['id']}", headers=h2)
    assert res.status == 404
