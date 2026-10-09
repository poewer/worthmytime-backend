"""Dokumentacja API: specyfikacja OpenAPI 3.1 (`/api/v1/openapi.json`) i Swagger UI (`/api/v1/docs`).

Schematy żądań pochodzą wprost z modeli Pydantic (`app/schemas.py`), więc nie rozjeżdżają się z walidacją.
Opisy operacji są w tabeli `OPERATIONS` poniżej; test `tests/test_openapi.py` pilnuje, żeby każdy endpoint
zarejestrowany w aplikacji był opisany (i odwrotnie), z poprawną nazwą handlera.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from . import schemas as s
from .routes_account import ChangePasswordIn, DeleteAccountIn

API_PREFIX = "/api/v1"

TAGS = [
    ("System", "Stan usługi i dokumentacja."),
    ("Uwierzytelnianie", "Rejestracja, logowanie, sesja w cookie i konto."),
    ("Kalkulator", "Przeliczanie ceny na czas pracy (bez konta) oraz porównania."),
    ("Historia", "Zapisane obliczenia, udostępnianie i podsumowanie."),
    ("Profil i budżet", "Stawka, plan budżetu, kredyty, prognoza i alerty."),
    ("Wydatki", "Rejestr wydatków i stałe wydatki."),
    ("Życzenia i cele", "Lista życzeń z okresem ostygnięcia oraz cele oszczędnościowe."),
]

# --- schematy odpowiedzi (opisowe; API zwraca zwykłe słowniki JSON) -----------------------------------------

_num = {"type": "number"}
_str = {"type": "string"}
_nullable_num = {"type": ["number", "null"]}


def _obj(props: dict[str, Any], required: list[str] | None = None, extra: bool = True) -> dict:
    out: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": extra}
    if required:
        out["required"] = required
    return out


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _list_of(name: str, **extra: Any) -> dict:
    return _obj({"items": {"type": "array", "items": _ref(name)}, **extra}, ["items"])


RESPONSE_SCHEMAS: dict[str, dict] = {
    "Error": _obj({"error": _str}, ["error"], extra=False),
    "ValidationError": _obj(
        {
            "error": _str,
            "errors": {
                "type": "array",
                "items": _obj({"field": _str, "message": _str}, ["field", "message"], extra=False),
            },
        },
        ["error"],
        extra=False,
    ),
    "Deleted": _obj({"deleted": {"type": "boolean"}}, ["deleted"]),
    "Health": _obj({"status": {"enum": ["ok", "unavailable"]}, "database": {"enum": ["up", "down"]}}, ["status"]),
    "Profile": _obj(
        {
            "currency": _str,
            "monthly_income": _nullable_num,
            "hourly_rate": _nullable_num,
            "hours_per_day": _num,
            "days_per_week": _num,
            "commute_minutes_per_day": _num,
            "work_costs_monthly": _num,
            "rate_mode": {"enum": ["NOMINAL", "REAL"]},
            "effective_hourly_rate": _nullable_num,
            "hours_per_month": _nullable_num,
        },
        ["currency"],
    ),
    "AuthResult": _obj({"token": _str, "profile": _ref("Profile")}, ["token", "profile"]),
    "Me": _obj({"id": _str, "email": _str, "profile": _ref("Profile")}, ["id", "email", "profile"]),
    "WorkTime": _obj(
        {
            "hours": _num,
            "hours_part": {"type": "integer"},
            "minutes_part": {"type": "integer"},
            "working_days": _num,
            "working_weeks": _num,
            "working_months": _num,
            "working_years": _num,
            "income_percent": _nullable_num,
        },
        ["hours"],
    ),
    "Result": _obj(
        {
            "type": {"enum": ["SIMPLE", "RECURRING", "TCO"]},
            "name": _str,
            "total_cost": _num,
            "hourly_rate": _nullable_num,
            "work": _ref("WorkTime"),
            "breakdown": {"type": "array", "items": _obj({"name": _str, "amount": _num})},
            "horizons": {"type": "array", "items": _obj({"label": _str, "cost": _num, "work": _ref("WorkTime")})},
            "life_cost": _obj({"years": _num, "per_day": _num, "per_week": _num, "per_month": _num}),
            "per_use": _obj({"uses": _num, "cost": _num, "work_minutes": _num}),
            "budget": _obj(
                {
                    "category": {"enum": ["NEEDS", "FUTURE", "GOALS", "FUN"]},
                    "warnings": {
                        "type": "array",
                        "items": _obj({"code": _str, "level": {"enum": ["info", "warning", "critical"]}, "params": _obj({})}),
                    },
                }
            ),
        },
        ["type", "name", "total_cost", "work"],
    ),
    "Calculation": _obj(
        {
            "id": _str,
            "name": _str,
            "type": {"enum": ["SIMPLE", "RECURRING", "TCO"]},
            "currency": _str,
            "public_id": {"type": ["string", "null"]},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            "input": _obj({}),
            "result": _ref("Result"),
        },
        ["name", "type", "result"],
    ),
    "CalculationList": _list_of(
        "Calculation", total={"type": "integer"}, next_cursor={"type": ["string", "null"], "description": "kursor kolejnej strony"}
    ),
    "SharedCalculation": _obj({"name": _str, "type": _str, "result": _ref("Result")}, ["name", "result"]),
    "ShareLink": _obj({"public_id": _str, "path": _str}, ["public_id", "path"]),
    "Comparison": _obj({"a": _ref("Result"), "b": _ref("Result"), "difference": _obj({})}),
    "Dashboard": _obj(
        {
            "currency": _str,
            "count": {"type": "integer"},
            "total_value": _num,
            "total_hours": _num,
            "total_working_days": _num,
            "largest_expense": {"type": ["object", "null"]},
            "recurring": {"type": "array", "items": _obj({})},
            "recurring_yearly_total": _num,
            "recent": {"type": "array", "items": _ref("Calculation")},
        }
    ),
    "Budget": _obj(
        {
            "percentages": _obj({c: _num for c in ("NEEDS", "FUTURE", "GOALS", "FUN")}),
            "spent": _obj({c: _num for c in ("NEEDS", "FUTURE", "GOALS", "FUN")}),
            "amounts": {"type": ["object", "null"]},
            "available": {"type": ["object", "null"]},
            "loans": {"type": "array", "items": _obj({"id": _str, "name": _str, "installment_amount": _num})},
            "monthly_loans": _num,
            "monthly_income": _nullable_num,
            "total_spent": _num,
            "is_custom": {"type": "boolean"},
        },
        ["percentages"],
    ),
    "Forecast": _obj(
        {
            "currency": _str,
            "today": {"type": "string", "format": "date"},
            "days_in_month": {"type": "integer"},
            "days_left": {"type": "integer"},
            "categories": {
                "type": "array",
                "items": _obj(
                    {
                        "category": _str,
                        "budget": _num,
                        "spent": _num,
                        "available": _num,
                        "daily_limit": _num,
                        "pace_per_day": _num,
                        "projected_total": _nullable_num,
                        "runs_out_on": {"type": ["string", "null"], "format": "date"},
                        "status": {"enum": ["OK", "WARN", "OVER"]},
                    }
                ),
            },
        }
    ),
    "Expense": _obj(
        {
            "id": _str,
            "category": {"enum": ["NEEDS", "FUTURE", "GOALS", "FUN"]},
            "amount": _num,
            "note": {"type": ["string", "null"]},
            "spent_on": {"type": "string", "format": "date"},
            "source_type": {"enum": ["RECURRING", "LOAN", None], "description": "pochodzenie wpisu; brak = ręczny"},
            "source_id": {"type": ["string", "null"]},
        },
        ["id", "category", "amount", "spent_on"],
    ),
    "ExpenseList": _list_of(
        "Expense", month={"type": "string"}, totals=_obj({}), total=_num, loan_payments={"type": "number"}
    ),
    "ExpenseSummary": _obj({"months": {"type": "array", "items": _obj({"month": _str, "totals": _obj({}), "total": _num})}}),
    "RecurringExpense": _obj(
        {
            "id": _str,
            "name": _str,
            "category": {"enum": ["NEEDS", "FUTURE", "GOALS", "FUN"]},
            "amount": _num,
            "day_of_month": {"type": "integer", "minimum": 1, "maximum": 31},
            "active": {"type": "boolean"},
            "start_date": {"type": "string", "format": "date"},
        },
        ["id", "name", "category", "amount", "day_of_month", "active"],
    ),
    "RecurringExpenseList": _list_of("RecurringExpense", monthly_total=_num),
    "Wish": _obj(
        {
            "id": _str,
            "name": _str,
            "price": _num,
            "category": {"type": ["string", "null"]},
            "cooldown_days": {"type": "integer"},
            "status": {"enum": ["WAITING", "BOUGHT", "DROPPED"]},
            "ready": {"type": "boolean"},
            "days_left": {"type": "integer"},
            "work": {"type": ["object", "null"]},
        },
        ["id", "name", "price", "status"],
    ),
    "WishList": _list_of("Wish", stats=_obj({}), currency=_str),
    "Goal": _obj(
        {
            "id": _str,
            "name": _str,
            "target_amount": _num,
            "saved_amount": _num,
            "monthly_contribution": _nullable_num,
            "target_date": {"type": ["string", "null"], "format": "date"},
            "percent": _num,
            "remaining": _num,
            "completed": {"type": "boolean"},
            "months_to_goal": _nullable_num,
            "on_track": {"type": ["boolean", "null"]},
        },
        ["id", "name", "target_amount", "saved_amount"],
    ),
    "GoalList": _list_of("Goal", currency=_str),
    "Alert": _obj(
        {
            "key": _str,
            "code": _str,
            "level": {"enum": ["info", "warning", "critical"]},
            "state": _str,
            "params": _obj({}),
            "link": _str,
        },
        ["key", "code", "level", "state", "link"],
    ),
    "AlertList": _list_of("Alert", count={"type": "integer"}, counts=_obj({})),
    "AccountExport": _obj(
        {
            "exported_at": {"type": "string", "format": "date-time"},
            "account": _obj({}),
            "calculations": {"type": "array", "items": _obj({})},
            "budget": {"type": ["object", "null"]},
            "loans": {"type": "array", "items": _obj({})},
            "expenses": {"type": "array", "items": _obj({})},
            "wishlist": {"type": "array", "items": _obj({})},
            "goals": {"type": "array", "items": _obj({})},
        }
    ),
}


# --- opis operacji ------------------------------------------------------------------------------------------

def _q(name: str, description: str, schema: dict | None = None, required: bool = False) -> dict:
    return {"name": name, "in": "query", "required": required, "description": description, "schema": schema or {"type": "string"}}


def _op(
    method: str,
    path: str,
    handler: str,
    tag: str,
    summary: str,
    ok: tuple[int, str, str | None] = (200, "OK", None),
    *,
    auth: bool = True,
    body: type[BaseModel] | None = None,
    query: list[dict] | None = None,
    description: str | None = None,
    extra: dict[int, str] | None = None,
) -> dict:
    return {
        "method": method,
        "path": path,
        "handler": handler,
        "tag": tag,
        "summary": summary,
        "ok": ok,
        "auth": auth,
        "body": body,
        "query": query or [],
        "description": description,
        "extra": extra or {},
    }


_CAT = {"enum": ["NEEDS", "FUTURE", "GOALS", "FUN"]}

OPERATIONS: list[dict] = [
    # System
    _op("GET", "/health", "health", "System", "Stan usługi i bazy danych", (200, "Usługa działa", "Health"), auth=False,
        description="Nie podlega limitom żądań (używany przez monitoring). `503`, gdy baza nie odpowiada.",
        extra={503: "Baza danych niedostępna"}),
    _op("GET", "/openapi.json", "openapi_json", "System", "Specyfikacja OpenAPI 3.1 (JSON)", (200, "Specyfikacja", None),
        auth=False),
    _op("GET", "/docs", "swagger_ui", "System", "Dokumentacja interaktywna (Swagger UI)", (200, "Strona HTML", None), auth=False,
        description="Swagger UI ładuje skrypty z CDN (jsdelivr), więc wymaga dostępu do internetu w przeglądarce."),
    # Uwierzytelnianie
    _op("POST", "/auth/register", "register", "Uwierzytelnianie", "Rejestracja konta", (201, "Konto utworzone", "AuthResult"),
        auth=False, body=s.Credentials,
        description="Ustawia cookie sesji `wmt_session` (HttpOnly) i `wmt_csrf`; token jest też w treści odpowiedzi.",
        extra={409: "Konto z tym adresem e-mail już istnieje"}),
    _op("POST", "/auth/login", "login", "Uwierzytelnianie", "Logowanie", (200, "Zalogowano", "AuthResult"), auth=False,
        body=s.Credentials,
        description="Po 5 nieudanych próbach na jedno konto z jednego adresu IP logowanie jest blokowane na 15 minut.",
        extra={401: "Nieprawidłowy e-mail lub hasło"}),
    _op("POST", "/auth/logout", "logout", "Uwierzytelnianie", "Wylogowanie (czyści cookie)", (200, "Wylogowano", None), auth=False),
    _op("POST", "/auth/session", "exchange_session", "Uwierzytelnianie", "Wymiana tokenu Bearer na cookie sesji",
        (200, "Cookie ustawione", None), auth=False,
        description="Migracja z tokenu w localStorage: wymaga ważnego nagłówka `Authorization: Bearer`.",
        extra={401: "Brak lub nieważny token"}),
    _op("GET", "/auth/me", "me", "Uwierzytelnianie", "Zalogowany użytkownik", (200, "Użytkownik i profil", "Me")),
    _op("POST", "/auth/change-password", "change_password", "Uwierzytelnianie", "Zmiana hasła", (200, "Hasło zmienione", None),
        body=ChangePasswordIn, extra={403: "Obecne hasło jest nieprawidłowe"}),
    _op("DELETE", "/account", "delete_account", "Uwierzytelnianie", "Usunięcie konta wraz z danymi", (200, "Konto usunięte", "Deleted"), body=DeleteAccountIn,
        description="Usuwa obliczenia (i publiczne linki), budżet, kredyty, wydatki, życzenia i cele. Wymaga hasła w treści.",
        extra={403: "Hasło jest nieprawidłowe"}),
    _op("GET", "/account/export", "export_account", "Uwierzytelnianie", "Eksport wszystkich danych użytkownika (RODO)",
        (200, "Dane użytkownika", "AccountExport")),
    # Kalkulator
    _op("POST", "/calculate", "calculate", "Kalkulator", "Przeliczenie zakupu na czas pracy (bez konta)",
        (200, "Wynik obliczeń", "Result"), auth=False, body=s.CalculateIn,
        description="Bezstanowe: profil i opcjonalny plan budżetu przesyłane w żądaniu, nic nie jest zapisywane."),
    _op("POST", "/compare", "compare", "Kalkulator", "Porównanie dwóch zakupów", (200, "Porównanie", "Comparison"), auth=False,
        body=s.CompareIn),
    # Historia
    _op("GET", "/calculations", "list_calculations", "Historia", "Historia obliczeń (paginacja, wyszukiwanie, sortowanie)",
        (200, "Strona historii", "CalculationList"),
        query=[
            _q("limit", "Rozmiar strony (1-200, domyślnie 100)", {"type": "integer", "minimum": 1, "maximum": 200}),
            _q("cursor", "Kursor z poprzedniej odpowiedzi (`next_cursor`)"),
            _q("q", "Fraza w nazwie (bez rozróżniania wielkości liter, do 100 znaków)"),
            _q("type", "Typ obliczenia", {"enum": ["SIMPLE", "RECURRING", "TCO"]}),
            _q("category", "Kategoria budżetu", _CAT),
            _q("sort", "Sortowanie", {"enum": ["created_desc", "created_asc", "name_asc", "name_desc"], "default": "created_desc"}),
        ]),
    _op("POST", "/calculations", "save_calculation", "Historia", "Zapis obliczenia", (201, "Zapisano", "Calculation"),
        body=s.CalculationIn),
    _op("GET", "/calculations/{calc_id}", "get_calculation", "Historia", "Szczegóły obliczenia", (200, "Obliczenie", "Calculation")),
    _op("PUT", "/calculations/{calc_id}", "update_calculation", "Historia", "Aktualizacja obliczenia",
        (200, "Zaktualizowano", "Calculation"), body=s.CalculationIn),
    _op("DELETE", "/calculations/{calc_id}", "delete_calculation", "Historia", "Usunięcie obliczenia", (200, "Usunięto", "Deleted")),
    _op("POST", "/calculations/{calc_id}/duplicate", "duplicate_calculation", "Historia", "Duplikat obliczenia",
        (201, "Kopia", "Calculation")),
    _op("POST", "/calculations/{calc_id}/share", "share", "Historia", "Włączenie publicznego linku", (200, "Link", "ShareLink")),
    _op("DELETE", "/calculations/{calc_id}/share", "unshare", "Historia", "Wyłączenie publicznego linku", (200, "Wyłączono", None)),
    _op("GET", "/shared/{public_id}", "shared", "Historia", "Publiczny wynik (bez stawki i profilu)",
        (200, "Wynik udostępniony", "SharedCalculation"), auth=False),
    _op("GET", "/dashboard", "dashboard", "Historia", "Podsumowanie historii", (200, "Podsumowanie", "Dashboard")),
    # Profil i budżet
    _op("GET", "/profile", "get_profile", "Profil i budżet", "Profil finansowy", (200, "Profil", "Profile")),
    _op("PUT", "/profile", "put_profile", "Profil i budżet", "Zapis profilu (dochód lub stawka, dojazd, koszty pracy)",
        (200, "Profil", "Profile"), body=s.ProfileIn),
    _op("GET", "/budget", "get_budget", "Profil i budżet", "Plan budżetu z wykorzystaniem kategorii i kredytami",
        (200, "Budżet", "Budget")),
    _op("PUT", "/budget", "put_budget", "Profil i budżet", "Zapis planu budżetu i kredytów", (200, "Budżet", "Budget"),
        body=s.BudgetIn, description="Procenty kategorii muszą sumować się do 100. Zapis tworzy raty od nowa (nowe identyfikatory)."),
    _op("GET", "/budget/forecast", "budget_forecast", "Profil i budżet", "Dzienny limit i prognoza końca miesiąca",
        (200, "Prognoza kategorii", "Forecast"), extra={409: "Brak dochodu lub stawki w profilu"}),
    _op("POST", "/budget/loans/{loan_id}/pay", "pay_loan_installment", "Profil i budżet",
        "Oznacz ratę kredytu jako opłaconą", (201, "Wpis o racie", "Expense"), body=s.LoanPaymentIn,
        description="Zapisuje wpis w Potrzebach (`source_type=LOAN`); nie liczy się drugi raz do wydanych.",
        extra={409: "Rata za ten miesiąc jest już opłacona"}),
    _op("GET", "/alerts", "list_alerts", "Profil i budżet", "Centrum alertów", (200, "Aktywne alerty", "AlertList")),
    _op("POST", "/alerts/{key}/dismiss", "dismiss_alert", "Profil i budżet", "Ukryj alert do zmiany jego stanu",
        (200, "Ukryto", None), description="`key` ma postać `KOD:przedmiot`, np. `CATEGORY_USAGE:FUN` (może być zakodowany procentowo)."),
    # Wydatki
    _op("GET", "/expenses", "list_expenses", "Wydatki", "Rejestr wydatków z miesiąca", (200, "Wpisy i sumy", "ExpenseList"),
        query=[_q("month", "Miesiąc `YYYY-MM` (domyślnie bieżący)")],
        description="Przy odczycie dopisują się brakujące wpisy ze stałych wydatków."),
    _op("POST", "/expenses", "add_expense", "Wydatki", "Dopisanie wydatku", (201, "Wpis", "Expense"), body=s.ExpenseIn),
    _op("PUT", "/expenses/{expense_id}", "update_expense", "Wydatki", "Edycja wpisu", (200, "Wpis", "Expense"), body=s.ExpenseIn,
        description="Zmienia kategorię, kwotę, notatkę i datę (brak `spent_on` zostawia dotychczasową); źródło wpisu się nie zmienia. "
        "Wpisu raty kredytu (`source_type=LOAN`) nie można edytować.",
        extra={409: "Wpis raty kredytu albo data zajęta przez ten sam stały wydatek"}),
    _op("DELETE", "/expenses/{expense_id}", "delete_expense", "Wydatki", "Usunięcie wpisu", (200, "Usunięto", "Deleted")),
    _op("GET", "/expenses/summary", "expenses_summary", "Wydatki", "Trend wydatków w ostatnich miesiącach",
        (200, "Podsumowanie miesięcy", "ExpenseSummary"),
        query=[_q("months", "Liczba miesięcy (1-24, domyślnie 6)", {"type": "integer", "minimum": 1, "maximum": 24})]),
    _op("GET", "/recurring-expenses", "list_recurring", "Wydatki", "Stałe wydatki", (200, "Szablony", "RecurringExpenseList")),
    _op("POST", "/recurring-expenses", "add_recurring", "Wydatki", "Dodanie stałego wydatku", (201, "Szablon", "RecurringExpense"),
        body=s.RecurringIn, description="Wpis w rejestrze powstaje sam w dniu płatności co miesiąc (31 = ostatni dzień)."),
    _op("PUT", "/recurring-expenses/{template_id}", "update_recurring", "Wydatki", "Zmiana stałego wydatku",
        (200, "Szablon", "RecurringExpense"), body=s.RecurringIn),
    _op("DELETE", "/recurring-expenses/{template_id}", "delete_recurring", "Wydatki", "Usunięcie stałego wydatku",
        (200, "Usunięto", "Deleted"), description="Wpisy już dopisane do rejestru zostają."),
    # Życzenia i cele
    _op("GET", "/wishlist", "get_wishlist", "Życzenia i cele", "Lista życzeń", (200, "Pozycje i statystyki", "WishList")),
    _op("POST", "/wishlist", "add_wish", "Życzenia i cele", "Dodanie do listy życzeń", (201, "Pozycja", "Wish"), body=s.WishIn),
    _op("DELETE", "/wishlist/{item_id}", "delete_wish", "Życzenia i cele", "Usunięcie pozycji", (200, "Usunięto", "Deleted")),
    _op("POST", "/wishlist/{item_id}/decision", "decide_wish", "Życzenia i cele", "Decyzja: kupuję lub odpuszczam",
        (200, "Pozycja po decyzji", "Wish"), body=s.DecisionIn, extra={409: "Decyzja została już podjęta"}),
    _op("GET", "/goals", "list_goals", "Życzenia i cele", "Cele oszczędnościowe", (200, "Cele", "GoalList")),
    _op("POST", "/goals", "add_goal", "Życzenia i cele", "Dodanie celu", (201, "Cel", "Goal"), body=s.GoalIn),
    _op("PUT", "/goals/{goal_id}", "update_goal", "Życzenia i cele", "Zmiana celu", (200, "Cel", "Goal"), body=s.GoalIn),
    _op("DELETE", "/goals/{goal_id}", "delete_goal", "Życzenia i cele", "Usunięcie celu", (200, "Usunięto", "Deleted")),
    _op("POST", "/goals/{goal_id}/deposit", "deposit", "Życzenia i cele", "Wpłata na cel (lub wypłata, gdy ujemna)",
        (200, "Cel po wpłacie", "Goal"), body=s.DepositIn),
]

_JSON = "application/json"


def _error_response(description: str, schema: str = "Error") -> dict:
    return {"description": description, "content": {_JSON: {"schema": _ref(schema)}}}


def _path_params(path: str) -> list[dict]:
    return [
        {"name": n, "in": "path", "required": True, "schema": {"type": "string"}, "description": "Identyfikator zasobu"}
        for n in re.findall(r"\{(\w+)\}", path)
    ]


def _body_schema(model: type[BaseModel], components: dict) -> dict:
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    for name, sub in schema.pop("$defs", {}).items():
        components.setdefault(name, sub)
    components[model.__name__] = schema
    return _ref(model.__name__)


def build_spec() -> dict:
    components: dict[str, dict] = deepcopy(RESPONSE_SCHEMAS)
    paths: dict[str, dict] = {}
    for o in OPERATIONS:
        status, ok_desc, ok_schema = o["ok"]
        responses: dict[str, Any] = {
            str(status): {"description": ok_desc}
            if ok_schema is None
            else {"description": ok_desc, "content": {_JSON: {"schema": _ref(ok_schema)}}}
        }
        if o["body"] is not None:
            responses["422"] = _error_response("Błędy walidacji (lista błędów per pole)", "ValidationError")
        if o["auth"]:
            responses["401"] = _error_response("Wymagane uwierzytelnienie")
            if o["method"] != "GET":
                responses["403"] = _error_response("Brak lub błędny token CSRF (przy sesji w cookie)")
        if "{" in o["path"]:
            responses["404"] = _error_response("Nie znaleziono zasobu")
        for code, text in o["extra"].items():
            responses[str(code)] = _error_response(text)
        responses["429"] = _error_response("Zbyt wiele żądań (nagłówek Retry-After)")

        operation: dict[str, Any] = {
            "tags": [o["tag"]],
            "summary": o["summary"],
            "operationId": o["handler"],
            "responses": responses,
        }
        if o["description"]:
            operation["description"] = o["description"]
        params = _path_params(o["path"]) + o["query"]
        if params:
            operation["parameters"] = params
        if o["body"] is not None:
            operation["requestBody"] = {
                "required": True,
                "content": {_JSON: {"schema": _body_schema(o["body"], components)}},
            }
        if o["auth"]:
            operation["security"] = [{"cookieAuth": []}, {"bearerAuth": []}]
        paths.setdefault(o["path"], {})[o["method"].lower()] = operation

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "WorthMyTime API",
            "version": "0.1.0",
            "description": (
                "REST API aplikacji finansowej WorthMyTime: przelicza zakupy na czas pracy i pomaga pilnować budżetu.\n\n"
                "**Uwierzytelnianie.** Po logowaniu serwer ustawia cookie `wmt_session` (HttpOnly) oraz `wmt_csrf`. "
                "Żądania zmieniające dane (POST, PUT, DELETE) uwierzytelnione cookie muszą odesłać wartość `wmt_csrf` "
                "w nagłówku `X-CSRF-Token`. Alternatywnie można używać nagłówka `Authorization: Bearer <token>` "
                "(bez CSRF), np. z narzędzi i skryptów.\n\n"
                "**Błędy** mają postać `{\"error\": \"...\"}`, a walidacja (422) dodatkowo `errors` z polami. "
                "Kwoty to liczby (zaokrąglane do groszy, ROUND_HALF_UP). Limity żądań zwracają `429` z `Retry-After`."
            ),
        },
        "servers": [{"url": API_PREFIX, "description": "Ten serwer"}],
        "tags": [{"name": n, "description": d} for n, d in TAGS],
        "paths": paths,
        "components": {
            "schemas": components,
            "securitySchemes": {
                "cookieAuth": {"type": "apiKey", "in": "cookie", "name": "wmt_session",
                               "description": "Sesja w cookie HttpOnly ustawiana przez logowanie."},
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            },
        },
    }


SWAGGER_UI_HTML = """<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WorthMyTime API: dokumentacja</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "%(spec_url)s",
      dom_id: "#swagger-ui",
      deepLinking: true,
      tagsSorter: "alpha",
      persistAuthorization: true,
    });
  </script>
</body>
</html>
"""


def sanic_to_openapi_path(path: str) -> str:
    """`api/v1/calculations/<calc_id:str>` -> `/calculations/{calc_id}` (bez prefiksu serwera)."""
    p = "/" + path.strip("/")
    p = re.sub(r"<(\w+)(?::\w+)?>", r"{\1}", p)
    return p[len(API_PREFIX):] if p.startswith(API_PREFIX) else p
