# ruff: noqa: F811
from datetime import date, timedelta

from app import alerts as rules
from app.budget import BudgetPlan
from app.helpers import today
from app.planning import add_months
from app.schemas import CATEGORIES, Category
from tests.test_api import PROFILE, _register, client  # noqa: F401


def _plan(income=10_000, spent=None, loans=0.0):
    plan = BudgetPlan(monthly_income=income, monthly_loans=loans)
    for category, value in (spent or {}).items():
        plan.spent[category] = value
    return plan


def test_category_usage_levels_at_80_and_100_percent():
    # budżety domyślne: Potrzeby 5000, Przyszłość 2500, Cele 1500, Przyjemności 1000
    assert rules.rule_category_usage(_plan(spent={Category.FUN: 799})) == []
    (warn,) = rules.rule_category_usage(_plan(spent={Category.FUN: 800}))
    assert (warn["key"], warn["level"], warn["state"]) == ("CATEGORY_USAGE:FUN", "warning", "80")
    assert warn["params"]["usage_percent"] == 80.0 and warn["params"]["available"] == 200
    (crit,) = rules.rule_category_usage(_plan(spent={Category.FUN: 1000}))
    assert (crit["level"], crit["state"]) == ("critical", "100")


def test_category_usage_counts_loans_in_needs_and_skips_zero_budgets():
    (a,) = rules.rule_category_usage(_plan(loans=4200))
    assert a["key"] == "CATEGORY_USAGE:NEEDS" and a["params"]["spent"] == 4200 and a["level"] == "warning"
    assert rules.rule_category_usage(_plan(income=0, loans=500)) == []
    assert len(CATEGORIES) == 4


def test_budget_deficit_when_spending_exceeds_income():
    assert rules.rule_budget_deficit(_plan(spent={Category.FUN: 10_000})) == []
    (a,) = rules.rule_budget_deficit(_plan(spent={Category.FUN: 9000}, loans=1500))
    assert (a["key"], a["level"], a["params"]["deficit"]) == ("BUDGET_DEFICIT", "critical", 500)
    assert rules.rule_budget_deficit(_plan(income=0, loans=500)) == []


def _loan(day, left=True, id_="l1"):
    return rules.LoanDue(id=id_, name="Kredyt", installment_amount=800, payment_day=day, has_installments_left=left)


def test_loan_due_within_three_days_and_not_paid():
    now = date(2026, 10, 10)
    assert rules.rule_loan_due([_loan(14)], set(), now) == []  # za 4 dni
    (a,) = rules.rule_loan_due([_loan(13)], set(), now)  # za 3 dni
    assert (a["level"], a["params"]["days_left"], a["state"]) == ("warning", 3, "2026-10-13")
    (today_alert,) = rules.rule_loan_due([_loan(10)], set(), now)
    assert today_alert["level"] == "critical" and today_alert["params"]["days_left"] == 0


def test_loan_due_skips_paid_finished_and_no_day():
    now = date(2026, 10, 10)
    assert rules.rule_loan_due([_loan(12)], {("l1", "2026-10")}, now) == []
    assert rules.rule_loan_due([_loan(12, left=False)], set(), now) == []
    assert rules.rule_loan_due([_loan(None)], set(), now) == []
    # rata za miesiąc przełomu: płatność za listopad nie wycisza alertu październikowego i odwrotnie
    assert len(rules.rule_loan_due([_loan(1)], {("l1", "2026-10")}, date(2026, 10, 30))) == 1
    assert rules.rule_loan_due([_loan(1)], {("l1", "2026-11")}, date(2026, 10, 30)) == []


def test_goal_schedule_overdue_and_off_track():
    now = date(2026, 10, 10)

    def goal(**kw):
        base = dict(id="g", name="Wakacje", completed=False, target_date=None, on_track=None, remaining=1000.0,
                    required_monthly=None)
        return rules.GoalState(**{**base, **kw})

    assert rules.rule_goal_schedule([goal()], now) == []  # brak terminu
    assert rules.rule_goal_schedule([goal(target_date=date(2026, 12, 1), on_track=True)], now) == []
    assert rules.rule_goal_schedule([goal(target_date=date(2026, 1, 1), completed=True)], now) == []
    (late,) = rules.rule_goal_schedule([goal(target_date=date(2026, 9, 1))], now)
    assert (late["code"], late["level"]) == ("GOAL_OVERDUE", "critical")
    (off,) = rules.rule_goal_schedule([goal(target_date=date(2027, 1, 1), on_track=False, required_monthly=400)], now)
    assert (off["code"], off["level"], off["params"]["required_monthly"]) == ("GOAL_OFF_TRACK", "warning", 400)


def test_wish_ready_sort_and_visibility():
    wishes = [
        {"id": "a", "name": "Monitor", "price": 900, "ready": True},
        {"id": "b", "name": "X", "price": 1, "ready": False},
    ]
    (w,) = rules.rule_wish_ready(wishes)
    assert (w["key"], w["level"]) == ("WISH_READY:a", "info")

    crit = rules.alert("B", None, rules.CRITICAL, "s", "/x")
    warn = rules.alert("A", None, rules.WARNING, "s", "/x")
    info = rules.alert("C", None, rules.INFO, "s", "/x")
    assert [a["key"] for a in rules.sort_alerts([info, warn, crit])] == ["B", "A", "C"]
    assert rules.visible([crit, warn], {"B": "s"}) == [warn]  # ukryty przy tym samym stanie
    assert rules.visible([crit], {"B": "inny"}) == [crit]  # stan się zmienił, więc alert wraca


def _spend(client, auth, amount, category="FUN"):
    client.post("/api/v1/expenses", json={"category": category, "amount": amount}, headers=auth)


def test_alerts_endpoint_dismiss_and_reappear_when_state_changes(client):
    auth = _register(client, "alerts@b.pl")
    assert client.get("/api/v1/alerts")[1].status == 401
    _, res = client.get("/api/v1/alerts", headers=auth)
    assert res.json["items"] == [] and res.json["count"] == 0  # nowe konto bez profilu: brak alertów i błędów

    client.put("/api/v1/profile", json=PROFILE, headers=auth)  # dochód 7000 -> Przyjemności 700
    _spend(client, auth, 600)  # 85,7%
    _, res = client.get("/api/v1/alerts", headers=auth)
    assert [a["key"] for a in res.json["items"]] == ["CATEGORY_USAGE:FUN"]
    assert res.json["counts"] == {"critical": 0, "warning": 1, "info": 0}
    assert res.json["items"][0]["link"] == "/budget" and res.json["items"][0]["state"] == "80"

    assert client.post("/api/v1/alerts/CATEGORY_USAGE:FUN/dismiss", headers=auth)[1].status == 200
    _, res = client.get("/api/v1/alerts", headers=auth)
    assert res.json["items"] == []

    _spend(client, auth, 200)  # 114%: stan zmienił się z 80 na 100, więc alert wraca jako krytyczny
    _, res = client.get("/api/v1/alerts", headers=auth)
    (a,) = res.json["items"]
    assert (a["level"], a["state"]) == ("critical", "100")
    client.post("/api/v1/alerts/CATEGORY_USAGE:FUN/dismiss", headers=auth)
    assert client.get("/api/v1/alerts", headers=auth)[1].json["items"] == []

    assert client.post("/api/v1/alerts/NIE_MA:X/dismiss", headers=auth)[1].status == 404
    other = _register(client, "alerts2@b.pl")  # ukrycie jest per użytkownik
    client.put("/api/v1/profile", json=PROFILE, headers=other)
    _spend(client, other, 650)
    assert len(client.get("/api/v1/alerts", headers=other)[1].json["items"]) == 1


def test_alerts_endpoint_loan_goal_and_wish(client):
    auth = _register(client, "alerts3@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    now = today()
    due_day = (now + timedelta(days=2)).day
    loan = {
        "name": "Kredyt auto",
        "installment_amount": 300,
        "installments_left": 12,
        "start_date": (now - timedelta(days=60)).isoformat(),
        "end_date": (now + timedelta(days=400)).isoformat(),
        "payment_day": due_day,
    }
    percentages = {"NEEDS": 50, "FUTURE": 20, "GOALS": 10, "FUN": 20}
    client.put("/api/v1/budget", json={"percentages": percentages, "loans": [loan]}, headers=auth)
    goal = {"name": "Dawny cel", "target_amount": 1000, "target_date": add_months(now, -1).isoformat()}
    client.post("/api/v1/goals", json=goal, headers=auth)
    client.post("/api/v1/wishlist", json={"name": "Monitor", "price": 900, "cooldown_days": 1}, headers=auth)

    _, res = client.get("/api/v1/alerts", headers=auth)
    codes = {a["code"] for a in res.json["items"]}
    assert {"LOAN_DUE", "GOAL_OVERDUE"} <= codes
    assert "WISH_READY" not in codes  # ostygnięcie trwa jeszcze dobę
    assert res.json["items"][0]["level"] == "critical"  # krytyczne na początku listy

    (loan_alert,) = [a for a in res.json["items"] if a["code"] == "LOAN_DUE"]
    loan_id = loan_alert["params"]["loan_id"]
    client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={"paid_on": loan_alert["params"]["due_date"]}, headers=auth)
    _, res = client.get("/api/v1/alerts", headers=auth)
    assert "LOAN_DUE" not in {a["code"] for a in res.json["items"]}  # opłacona rata wycisza alert


def test_dismiss_accepts_percent_encoded_key(client):
    auth = _register(client, "alerts4@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    _spend(client, auth, 600)
    _, res = client.post("/api/v1/alerts/CATEGORY_USAGE%3AFUN/dismiss", headers=auth)  # tak wysyła ją przeglądarka
    assert res.status == 200 and res.json["dismissed"] == "CATEGORY_USAGE:FUN"
    assert client.get("/api/v1/alerts", headers=auth)[1].json["items"] == []
