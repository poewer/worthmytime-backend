# ruff: noqa: F811
from datetime import date, timedelta

from app.helpers import today
from app.planning import add_months
from app.recurring import due_date, due_dates
from tests.test_api import PROFILE, _register, client  # noqa: F401


def test_due_date_clamps_to_month_length():
    assert due_date(2026, 2, 31) == date(2026, 2, 28)
    assert due_date(2028, 2, 31) == date(2028, 2, 29)  # rok przestÄ™pny
    assert due_date(2026, 4, 31) == date(2026, 4, 30)
    assert due_date(2026, 5, 31) == date(2026, 5, 31)


def test_due_dates_backfill_from_start_date_and_skip_future():
    got = list(due_dates(15, date(2026, 1, 20), None, date(2026, 4, 10)))
    assert got == [date(2026, 2, 15), date(2026, 3, 15)]  # styczeĹ„ przed startem, kwiecieĹ„ jeszcze nie nadszedĹ‚
    assert list(due_dates(15, date(2026, 1, 20), None, date(2026, 4, 15)))[-1] == date(2026, 4, 15)


def test_due_dates_never_repeat_after_generated_through():
    start, now = date(2026, 1, 1), date(2026, 4, 20)
    first = list(due_dates(5, start, None, now))
    assert first == [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5), date(2026, 4, 5)]
    assert list(due_dates(5, start, now, now)) == []  # ponowne wywoĹ‚anie po dopisaniu nic nie daje
    assert list(due_dates(5, start, date(2026, 2, 5), now)) == [date(2026, 3, 5), date(2026, 4, 5)]


def test_due_dates_day_31_in_short_months():
    got = list(due_dates(31, date(2026, 1, 1), None, date(2026, 4, 30)))
    assert got == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_due_dates_backfill_is_capped():
    got = list(due_dates(1, date(2000, 1, 1), None, date(2026, 10, 6)))
    assert len(got) <= 38


def _template(**over):
    body = {"name": "Czynsz", "category": "NEEDS", "amount": 2000, "day_of_month": 1}
    return {**body, **over}


def test_recurring_expense_appears_in_ledger_and_reduces_budget(client):
    auth = _register(client, "rec@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    start = add_months(today().replace(day=1), -2)  # dwa miesiÄ…ce wstecz, termin 1. dnia miesiÄ…ca
    _, res = client.post("/api/v1/recurring-expenses", json=_template(start_date=start.isoformat()), headers=auth)
    assert res.status == 201 and res.json["day_of_month"] == 1

    _, res = client.get("/api/v1/expenses", headers=auth)  # bieĹĽÄ…cy miesiÄ…c
    items = res.json["items"]
    assert [(e["note"], e["amount"], e["source_type"]) for e in items] == [("Czynsz", 2000, "RECURRING")]
    assert res.json["totals"]["NEEDS"] == 2000

    # idempotentnie: kolejne odczyty nie dopisujÄ… duplikatĂłw
    for _ in range(3):
        client.get("/api/v1/expenses", headers=auth)
        client.get("/api/v1/budget", headers=auth)
    _, res = client.get("/api/v1/expenses", headers=auth)
    assert len(res.json["items"]) == 1
    _, res = client.get("/api/v1/expenses/summary?months=3", headers=auth)
    assert [m["total"] for m in res.json["months"]] == [2000, 2000, 2000]  # trzy miesiÄ…ce z wpisem

    # wydatek zmniejsza dostÄ™pny budĹĽet kategorii
    _, res = client.get("/api/v1/budget", headers=auth)
    assert res.json["spent"]["NEEDS"] == 2000


def test_new_template_does_not_backfill_and_is_listed(client):
    auth = _register(client, "rec2@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    # termin już minięty w tym miesiącu (albo dopiero w przyszłości, gdy dziś jest 1.): bez start_date nic nie powstaje
    not_due = today().day - 1 if today().day > 1 else 28
    client.post("/api/v1/recurring-expenses", json=_template(day_of_month=not_due), headers=auth)
    gym = _template(name="Siłownia", day_of_month=28, amount=100)
    client.post("/api/v1/recurring-expenses", json=gym, headers=auth)
    _, res = client.get("/api/v1/expenses", headers=auth)
    assert [e["note"] for e in res.json["items"]] == (["Siłownia"] if today().day == 28 else [])
    _, res = client.get("/api/v1/recurring-expenses", headers=auth)
    assert res.json["monthly_total"] == 2100 and len(res.json["items"]) == 2


def test_disabled_template_generates_nothing_and_reenable_does_not_backfill(client):
    auth = _register(client, "rec3@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    start = add_months(today().replace(day=1), -3).isoformat()
    _, res = client.post("/api/v1/recurring-expenses", json=_template(active=False, start_date=start), headers=auth)
    tid = res.json["id"]
    _, res = client.get("/api/v1/expenses", headers=auth)
    assert res.json["items"] == []
    _, res = client.get("/api/v1/recurring-expenses", headers=auth)
    assert res.json["monthly_total"] == 0  # wyĹ‚Ä…czony szablon nie liczy siÄ™ do sumy

    client.put(f"/api/v1/recurring-expenses/{tid}", json=_template(active=True, start_date=start), headers=auth)
    _, res = client.get("/api/v1/expenses/summary?months=6", headers=auth)
    assert all(m["total"] == 0 for m in res.json["months"])  # okres wyĹ‚Ä…czenia nie zostaĹ‚ dopisany


def test_deleting_generated_entry_is_not_regenerated_and_template_delete_keeps_entries(client):
    auth = _register(client, "rec4@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    start = today().replace(day=1)
    _, res = client.post("/api/v1/recurring-expenses", json=_template(start_date=start.isoformat()), headers=auth)
    tid = res.json["id"]
    _, res = client.get("/api/v1/expenses", headers=auth)
    eid = res.json["items"][0]["id"]
    assert client.delete(f"/api/v1/expenses/{eid}", headers=auth)[1].status == 200
    _, res = client.get("/api/v1/expenses", headers=auth)
    assert res.json["items"] == []  # usuniÄ™ty wpis nie wraca

    assert client.delete(f"/api/v1/recurring-expenses/{tid}", headers=auth)[1].status == 200
    assert client.delete(f"/api/v1/recurring-expenses/{tid}", headers=auth)[1].status == 404


def test_recurring_validation_and_isolation(client):
    auth = _register(client, "rec5@b.pl")
    other = _register(client, "rec6@b.pl")
    for bad in (_template(day_of_month=0), _template(day_of_month=32), _template(amount=0), _template(category="X")):
        assert client.post("/api/v1/recurring-expenses", json=bad, headers=auth)[1].status == 422
    assert client.get("/api/v1/recurring-expenses")[1].status == 401
    _, res = client.post("/api/v1/recurring-expenses", json=_template(), headers=auth)
    tid = res.json["id"]
    assert client.put(f"/api/v1/recurring-expenses/{tid}", json=_template(), headers=other)[1].status == 404
    assert client.delete(f"/api/v1/recurring-expenses/{tid}", headers=other)[1].status == 404


def _loan_budget(client, auth):
    start = (today() - timedelta(days=90)).isoformat()
    end = (today() + timedelta(days=500)).isoformat()
    loan = {
        "name": "Kredyt auto",
        "installment_amount": 800,
        "installments_left": 10,
        "start_date": start,
        "end_date": end,
        "payment_day": 10,
    }
    percentages = {"NEEDS": 50, "FUTURE": 20, "GOALS": 10, "FUN": 20}
    client.put("/api/v1/budget", json={"percentages": percentages, "loans": [loan]}, headers=auth)
    _, res = client.get("/api/v1/budget", headers=auth)
    return res.json["loans"][0]["id"]


def test_pay_loan_installment_creates_needs_entry_once_per_month(client):
    auth = _register(client, "loan@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    loan_id = _loan_budget(client, auth)
    _, before = client.get("/api/v1/budget", headers=auth)
    needs_before = (before.json["spent"]["NEEDS"], before.json["available"]["NEEDS"])

    _, res = client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={}, headers=auth)
    assert res.status == 201
    assert (res.json["category"], res.json["amount"], res.json["source_type"]) == ("NEEDS", 800, "LOAN")
    assert client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={}, headers=auth)[1].status == 409

    _, res = client.get("/api/v1/expenses", headers=auth)
    assert [e["note"] for e in res.json["items"]] == ["Rata: Kredyt auto"]
    assert res.json["total"] == 0 and res.json["loan_payments"] == 800  # rata nie liczy siÄ™ podwĂłjnie
    _, after = client.get("/api/v1/budget", headers=auth)
    assert (after.json["spent"]["NEEDS"], after.json["available"]["NEEDS"]) == needs_before

    # inny miesiÄ…c: moĹĽna zapĹ‚aciÄ‡ ponownie; cofniÄ™cie wpisu odblokowuje miesiÄ…c
    prev = add_months(today().replace(day=10), -1).isoformat()
    assert client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={"paid_on": prev}, headers=auth)[1].status == 201

    other = _register(client, "loan2@b.pl")
    assert client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={}, headers=other)[1].status == 404



