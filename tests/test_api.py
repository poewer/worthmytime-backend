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

    good = {"percentages": {"NEEDS": 40, "FUTURE": 25, "GOALS": 15, "FUN": 20}}
    _, res = client.put("/api/v1/budget", json=good, headers=auth)
    assert res.json["amounts"]["FUN"] == 2000 and res.json["is_custom"] is True

    # wydane pochodzą wyłącznie z rejestru wydatków; "spent" w PUT /budget jest ignorowane
    client.put("/api/v1/budget", json={**good, "spent": {"FUN": 999}}, headers=auth)
    _, res = client.get("/api/v1/budget", headers=auth)
    assert res.json["spent"]["FUN"] == 0
    _, res = client.post("/api/v1/expenses", json={"category": "FUN", "amount": 1500}, headers=auth)
    expense_id = res.json["id"]

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
    calc_id = res.json["id"]
    client.delete(f"/api/v1/expenses/{expense_id}", headers=auth)
    _, res = client.get(f"/api/v1/calculations/{calc_id}", headers=auth)
    assert res.json["result"]["budget"]["fits_budget"] is True


def test_loans_are_saved_with_budget_and_counted_in_needs(client):
    _, res = client.post("/api/v1/auth/register", json={"email": "loan@b.pl", "password": "supersecret1"})
    auth = {"Authorization": f"Bearer {res.json['token']}"}
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)
    body = {
        "percentages": {"NEEDS": 50, "FUTURE": 25, "GOALS": 15, "FUN": 10},
        "loans": [
            {"name": "Kredyt gotówkowy", "installment_amount": 800, "installments_left": 36, "loan_amount": 40000},
            {"name": "Karta", "installment_amount": 400, "installments_left": 6},
        ],
    }
    _, res = client.put("/api/v1/budget", json=body, headers=auth)
    assert res.status == 200
    client.post("/api/v1/expenses", json={"category": "NEEDS", "amount": 2000}, headers=auth)
    assert res.json["monthly_loans"] == 1200 and res.json["loans_income_percent"] == 12.0
    first = res.json["loans"][0]
    assert first["remaining_to_pay"] == 28800 and first["remaining_work_hours"] > 0
    assert res.json["last_installment_in_months"] == 36

    fridge = {"name": "Lodówka", "purchase_price": 1000, "category": "NEEDS"}
    _, res = client.post("/api/v1/calculate", json={"calculation": fridge}, headers=auth)
    assert res.json["budget"]["spent"] == 3200  # wydatki 2 000 + raty 1 200
    assert res.json["budget"]["obligations"]["monthly_installments"] == 1200

    # zapis planu bez kredytów usuwa je
    client.put("/api/v1/budget", json={**body, "loans": []}, headers=auth)
    _, res = client.get("/api/v1/budget", headers=auth)
    assert res.json["loans"] == [] and res.json["monthly_loans"] == 0


def _register(client, email):
    _, res = client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret1"})
    return {"Authorization": f"Bearer {res.json['token']}"}


def test_expense_ledger_feeds_budget_and_summary(client):
    auth = _register(client, "ledger@b.pl")
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)
    pct = {"NEEDS": 50, "FUTURE": 25, "GOALS": 15, "FUN": 10}
    client.put("/api/v1/budget", json={"percentages": pct}, headers=auth)

    _, res = client.post("/api/v1/expenses", json={"category": "FUN", "amount": 200, "note": "kino"}, headers=auth)
    assert res.status == 201
    expense_id = res.json["id"]
    _, res = client.get("/api/v1/expenses", headers=auth)
    assert res.json["total"] == 200 and res.json["totals"]["FUN"] == 200 and len(res.json["items"]) == 1

    _, res = client.get("/api/v1/budget", headers=auth)
    assert res.json["spent"]["FUN"] == 200  # wydane = tylko rejestr wydatków

    body = {"calculation": {"name": "Gra", "purchase_price": 500, "category": "FUN"}}
    _, res = client.post("/api/v1/calculate", json=body, headers=auth)
    assert res.json["budget"]["spent"] == 200 and res.json["budget"]["available"] == 800

    _, res = client.get("/api/v1/expenses/summary?months=3", headers=auth)
    assert len(res.json["months"]) == 3 and res.json["months"][-1]["totals"]["FUN"] == 200
    assert client.get("/api/v1/expenses/summary?months=abc", headers=auth)[1].status == 422
    assert client.get("/api/v1/expenses?month=2026-13", headers=auth)[1].status == 422
    assert client.post("/api/v1/expenses", json={"category": "FUN", "amount": -5}, headers=auth)[1].status == 422

    other = _register(client, "ledger2@b.pl")
    assert client.delete(f"/api/v1/expenses/{expense_id}", headers=other)[1].status == 404
    assert client.delete(f"/api/v1/expenses/{expense_id}", headers=auth)[1].status == 200
    _, res = client.get("/api/v1/expenses", headers=auth)
    assert res.json["total"] == 0


def test_max_monthly_contribution_from_category_availability(client):
    auth = _register(client, "contrib@b.pl")
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)
    client.post("/api/v1/expenses", json={"category": "FUN", "amount": 200}, headers=auth)  # FUN: 1 000 - 200 = 800

    def calc(**extra):
        body = {"calculation": {"name": "Konsola", "purchase_price": 3200, "category": "FUN", **extra}}
        return client.post("/api/v1/calculate", json=body, headers=auth)[1].json["budget"]

    b = calc()  # bez własnej wpłaty: automatycznie maksimum z kategorii
    assert b["upfront"]["max_monthly_contribution"] == 800
    assert b["upfront"]["monthly_contribution"] == 800 and b["upfront"]["contribution_source"] == "CATEGORY_AVAILABLE"
    assert b["upfront"]["months_to_goal"] == 4.0

    ok_plan = calc(monthly_contribution=500)  # w ramach maksimum: odkładanie w czasie mieści się w budżecie
    assert ok_plan["fits_budget"] is True and ok_plan["upfront"]["contribution_source"] == "USER"
    assert "CATEGORY_BUDGET_EXCEEDED" not in {w["code"] for w in ok_plan["warnings"]}

    too_much = calc(monthly_contribution=1000)
    assert too_much["fits_budget"] is False
    w = next(w for w in too_much["warnings"] if w["code"] == "CONTRIBUTION_EXCEEDS_AVAILABLE")
    assert w["params"]["max_monthly"] == 800 and w["params"]["overrun"] == 200


def test_goal_in_category_gets_max_contribution_shared_with_other_goals(client):
    auth = _register(client, "goalcat@b.pl")
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)
    client.post("/api/v1/expenses", json={"category": "FUN", "amount": 200}, headers=auth)  # wolne 800

    goal = {"name": "Konsola", "target_amount": 3200, "category": "FUN"}
    _, res = client.post("/api/v1/goals", json=goal, headers=auth)
    g = res.json
    assert g["max_monthly_contribution"] == 800 and g["effective_contribution"] == 800
    assert g["contribution_source"] == "CATEGORY_AVAILABLE" and g["months_to_goal"] == 4.0

    bike = {"name": "Rower", "target_amount": 2000, "category": "FUN", "monthly_contribution": 500}
    _, res = client.post("/api/v1/goals", json=bike, headers=auth)
    assert res.json["contribution_exceeds"] is False
    _, res = client.get("/api/v1/goals", headers=auth)
    by_name = {x["name"]: x for x in res.json["items"]}
    # Rower zarezerwował 500, więc na Konsolę zostaje 300 (wolne 800 - 500)
    assert by_name["Konsola"]["max_monthly_contribution"] == 300
    assert by_name["Konsola"]["months_to_goal"] == round(3200 / 300, 1)
    # Konsola nie ma własnej wpłaty, więc nie blokuje limitu Roweru
    assert by_name["Rower"]["max_monthly_contribution"] == 800

    too_big = {**bike, "name": "Motor", "monthly_contribution": 900}
    _, res = client.post("/api/v1/goals", json=too_big, headers=auth)
    assert res.json["contribution_exceeds"] is True  # 900 > 800 - 500 (Rower)


def test_wishlist_cooldown_decision_and_savings(client):
    auth = _register(client, "wish@b.pl")
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)

    body = {"name": "PlayStation", "price": 2500, "cooldown_days": 0}
    _, res = client.post("/api/v1/wishlist", json=body, headers=auth)
    assert res.status == 201 and res.json["ready"] is True and res.json["work"]["hours"] > 43
    ready_id = res.json["id"]
    _, res = client.post("/api/v1/wishlist", json={"name": "Rower", "price": 3000}, headers=auth)
    assert res.json["ready"] is False and res.json["days_left"] == 30 and res.json["cooldown_days"] == 30

    decide = f"/api/v1/wishlist/{ready_id}/decision"
    _, res = client.post(decide, json={"decision": "DROPPED"}, headers=auth)
    assert res.json["status"] == "DROPPED" and res.json["decided_at"]
    assert client.post(decide, json={"decision": "BOUGHT"}, headers=auth)[1].status == 409
    assert client.post(decide, json={"decision": "XYZ"}, headers=auth)[1].status == 422

    _, res = client.get("/api/v1/wishlist", headers=auth)
    stats = res.json["stats"]
    assert stats["dropped_total"] == 2500 and stats["dropped_hours"] > 43 and stats["waiting_count"] == 1
    other = _register(client, "wish2@b.pl")
    assert client.delete(f"/api/v1/wishlist/{ready_id}", headers=other)[1].status == 404
    assert client.delete(f"/api/v1/wishlist/{ready_id}", headers=auth)[1].status == 200


def test_savings_goals_progress_and_deposits(client):
    auth = _register(client, "goal@b.pl")
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)
    goal = {"name": "Wakacje", "target_amount": 5000, "saved_amount": 500, "monthly_contribution": 1000}
    _, res = client.post("/api/v1/goals", json=goal, headers=auth)
    assert res.status == 201
    assert res.json["months_to_goal"] == 4.5 and res.json["percent"] == 10.0 and res.json["completed"] is False
    gid = res.json["id"]

    deposit = f"/api/v1/goals/{gid}/deposit"
    _, res = client.post(deposit, json={"amount": 1000}, headers=auth)
    assert res.json["saved_amount"] == 1500 and res.json["remaining"] == 3500
    assert client.post(deposit, json={"amount": 0}, headers=auth)[1].status == 422
    assert client.post(deposit, json={"amount": -9999}, headers=auth)[1].status == 422

    _, res = client.post(deposit, json={"amount": 3500}, headers=auth)
    assert res.json["completed"] is True and res.json["remaining"] == 0
    _, res = client.post(deposit, json={"amount": -100}, headers=auth)
    assert res.json["completed"] is False  # wypłata cofa ukończenie

    _, res = client.put(f"/api/v1/goals/{gid}", json={**goal, "name": "Wakacje 2027"}, headers=auth)
    assert res.json["name"] == "Wakacje 2027"
    other = _register(client, "goal2@b.pl")
    assert client.delete(f"/api/v1/goals/{gid}", headers=other)[1].status == 404
    _, res = client.get("/api/v1/goals", headers=auth)
    assert len(res.json["items"]) == 1


def test_real_hourly_rate_profile_and_saved_calculation(client):
    auth = _register(client, "real@b.pl")
    profile = {"monthly_income": 10000, "commute_minutes_per_day": 90, "work_costs_monthly": 600}
    _, res = client.put("/api/v1/profile", json=profile, headers=auth)
    assert res.json["nominal_hourly_rate"] == 57.69 and res.json["real_hourly_rate"] == 45.67
    assert res.json["effective_hourly_rate"] == 57.69  # tryb NOMINAL

    _, res = client.put("/api/v1/profile", json={**profile, "rate_mode": "REAL"}, headers=auth)
    assert res.json["effective_hourly_rate"] == 45.67 and res.json["rate_mode"] == "REAL"

    _, res = client.post("/api/v1/calculations", json={"name": "x", "purchase_price": 2000}, headers=auth)
    assert res.json["result"]["work"]["hours"] > 43.4  # realnie więcej godzin niż 34,7 h nominalnie
    assert res.json["result"]["work"]["income_percent"] == 20.0  # udział liczony od dochodu netto
    _, res = client.get(f"/api/v1/calculations/{res.json['id']}", headers=auth)
    assert res.json["result"]["work"]["income_percent"] == 20.0  # także po odczycie z migawki


def test_cost_per_use_in_api(client):
    body = {"profile": PROFILE, "calculation": {"name": "Rower", "purchase_price": 3000, "expected_uses": 300}}
    _, res = client.post("/api/v1/calculate", json=body)
    assert res.json["per_use"]["cost"] == 10.0 and res.json["per_use"]["work_minutes"] > 0
    body["calculation"]["expected_uses"] = 0
    assert client.post("/api/v1/calculate", json=body)[1].status == 422


def test_loan_dates_payment_day_and_derived_schedule(client):
    from datetime import date, timedelta

    from app.planning import add_months

    auth = _register(client, "loandates@b.pl")
    client.put("/api/v1/profile", json={"monthly_income": 10000}, headers=auth)
    pct = {"NEEDS": 50, "FUTURE": 25, "GOALS": 15, "FUN": 10}
    now = date.today()
    start = add_months(now, -6, 1)
    end = add_months(now, 11, 20)
    loan = {
        "name": "Kredyt",
        "installment_amount": 800,
        "loan_amount": 20000,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "payment_day": 20,
    }  # brak installments_left - liczone z daty końca
    _, res = client.put("/api/v1/budget", json={"percentages": pct, "loans": [loan]}, headers=auth)
    assert res.status == 200
    v = res.json["loans"][0]
    assert 11 <= v["installments_left"] <= 13
    assert v["payment_day"] == 20 and v["end_date"] == end.isoformat() and v["start_date"] == start.isoformat()
    assert date.fromisoformat(v["next_payment_date"]).day == 20
    assert 0 <= v["days_to_next_payment"] <= 31
    assert v["last_payment_date"] == end.isoformat() and v["finished"] is False
    assert 0 < v["repayment_progress_percent"] < 100
    assert v["remaining_to_pay"] == 800 * v["installments_left"]
    assert res.json["monthly_loans"] == 800

    # kredyt z datą końca w przeszłości jest spłacony i nie obciąża budżetu
    past = {
        **loan,
        "end_date": (now - timedelta(days=40)).isoformat(),
        "start_date": (now - timedelta(days=400)).isoformat(),
    }
    _, res = client.put("/api/v1/budget", json={"percentages": pct, "loans": [past]}, headers=auth)
    assert res.json["loans"][0]["finished"] is True and res.json["loans"][0]["installments_left"] == 0
    assert res.json["monthly_loans"] == 0 and res.json["last_installment_in_months"] == 0

    # walidacja: potrzebna liczba rat albo data końca; koniec nie może być przed początkiem; dzień raty 1-31
    bad = [
        {"name": "x", "installment_amount": 100},
        {**loan, "end_date": (start - timedelta(days=1)).isoformat()},
        {**loan, "payment_day": 32},
        {"name": "x", "installment_amount": 100, "installments_left": 12, "payment_day": 0},
    ]
    for b in bad:
        _, res = client.put("/api/v1/budget", json={"percentages": pct, "loans": [b]}, headers=auth)
        assert res.status == 422, b

    # stara forma (sama liczba rat) nadal działa
    _, res = client.put(
        "/api/v1/budget",
        json={"percentages": pct, "loans": [{"name": "x", "installment_amount": 100, "installments_left": 12}]},
        headers=auth,
    )
    assert res.status == 200 and res.json["loans"][0]["installments_left"] == 12
    assert res.json["loans"][0]["next_payment_date"] is not None


def test_other_user_cannot_read(client):
    _, r1 = client.post("/api/v1/auth/register", json={"email": "u1@b.pl", "password": "supersecret1"})
    _, r2 = client.post("/api/v1/auth/register", json={"email": "u2@b.pl", "password": "supersecret1"})
    h1 = {"Authorization": f"Bearer {r1.json['token']}"}
    h2 = {"Authorization": f"Bearer {r2.json['token']}"}
    client.put("/api/v1/profile", json=PROFILE, headers=h1)
    _, c = client.post("/api/v1/calculations", json={"name": "x", "purchase_price": 1}, headers=h1)
    _, res = client.get(f"/api/v1/calculations/{c.json['id']}", headers=h2)
    assert res.status == 404
