# ruff: noqa: F811
from app.helpers import today
from app.planning import add_months, period_of
from tests.test_api import PROFILE, _register, client  # noqa: F401
from tests.test_recurring import _loan_budget, _template

URL = "/api/v1/expenses"


def test_edit_changes_all_fields_and_recomputes_totals(client):
    auth = _register(client, "edit1@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    first = today().replace(day=1).isoformat()
    _, res = client.post(URL, json={"category": "FUN", "amount": 100, "note": "kino"}, headers=auth)
    eid = res.json["id"]

    _, res = client.put(
        f"{URL}/{eid}",
        json={"category": "NEEDS", "amount": 250.5, "note": "czynsz", "spent_on": first},
        headers=auth,
    )
    assert res.status == 200
    assert (res.json["category"], res.json["amount"], res.json["note"], res.json["spent_on"]) == (
        "NEEDS",
        250.5,
        "czynsz",
        first,
    )

    _, listed = client.get(URL, headers=auth)
    assert listed.json["totals"]["NEEDS"] == 250.5 and listed.json["totals"]["FUN"] == 0
    assert len(listed.json["items"]) == 1  # edycja nie dopisuje drugiego wpisu


def test_edit_without_date_keeps_existing_date_and_clears_note(client):
    auth = _register(client, "edit2@b.pl")
    first = today().replace(day=1).isoformat()
    _, res = client.post(URL, json={"category": "FUN", "amount": 10, "note": "x", "spent_on": first}, headers=auth)
    eid = res.json["id"]

    _, res = client.put(f"{URL}/{eid}", json={"category": "FUN", "amount": 12}, headers=auth)
    assert res.status == 200
    assert res.json["spent_on"] == first and res.json["note"] is None and res.json["amount"] == 12


def test_edit_validates_and_is_private_to_owner(client):
    auth = _register(client, "edit3@b.pl")
    _, res = client.post(URL, json={"category": "FUN", "amount": 10}, headers=auth)
    eid = res.json["id"]

    assert client.put(f"{URL}/{eid}", json={"category": "FUN", "amount": -5}, headers=auth)[1].status == 422
    other = _register(client, "edit4@b.pl")
    assert client.put(f"{URL}/{eid}", json={"category": "FUN", "amount": 99}, headers=other)[1].status == 404
    assert client.put(f"{URL}/nie-ma", json={"category": "FUN", "amount": 99}, headers=auth)[1].status == 404
    _, listed = client.get(URL, headers=auth)
    assert listed.json["items"][0]["amount"] == 10  # nieudane edycje niczego nie zmieniły


def test_edit_recurring_entry_keeps_source_and_rejects_taken_date(client):
    auth = _register(client, "edit5@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    start = add_months(today().replace(day=1), -2)
    client.post("/api/v1/recurring-expenses", json=_template(start_date=start.isoformat()), headers=auth)

    _, listed = client.get(URL, headers=auth)
    (current,) = listed.json["items"]
    assert current["source_type"] == "RECURRING"

    _, res = client.put(f"{URL}/{current['id']}", json={"category": "NEEDS", "amount": 1500}, headers=auth)
    assert res.status == 200
    assert res.json["amount"] == 1500
    assert (res.json["source_type"], res.json["source_id"]) == ("RECURRING", current["source_id"])

    # ta sama pozycja stałego wydatku ma już wpis z poprzedniego miesiąca: przeniesienie na jego datę to 409
    prev = period_of(add_months(today().replace(day=1), -1))
    (earlier,) = client.get(f"{URL}?month={prev}", headers=auth)[1].json["items"]
    clash = {"category": "NEEDS", "amount": 1500, "spent_on": earlier["spent_on"]}
    assert client.put(f"{URL}/{current['id']}", json=clash, headers=auth)[1].status == 409
    _, listed = client.get(URL, headers=auth)
    assert listed.json["items"][0]["spent_on"] == current["spent_on"]  # po błędzie wpis jest nietknięty


def test_loan_payment_entry_cannot_be_edited(client):
    auth = _register(client, "edit6@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    loan_id = _loan_budget(client, auth)
    client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={}, headers=auth)

    _, listed = client.get(URL, headers=auth)
    (rata,) = listed.json["items"]
    assert rata["source_type"] == "LOAN"
    _, res = client.put(f"{URL}/{rata['id']}", json={"category": "FUN", "amount": 1}, headers=auth)
    assert res.status == 409
    assert client.get(URL, headers=auth)[1].json["loan_payments"] == 800  # rata bez zmian
