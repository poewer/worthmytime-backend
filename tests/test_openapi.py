# ruff: noqa: F811
import pytest
from openapi_spec_validator import validate

from app.main import app as real_app
from app.openapi import OPERATIONS, build_spec, sanic_to_openapi_path
from tests.test_api import client  # noqa: F401


def _registered() -> dict[tuple[str, str], str]:
    """(METODA, ścieżka OpenAPI) -> nazwa handlera, z routera aplikacji."""
    found = {}
    for route in real_app.router.routes:
        for method in route.methods:
            if method in ("OPTIONS", "HEAD"):
                continue
            found[(method, sanic_to_openapi_path(route.path))] = route.handler.__name__
    return found


def _documented() -> dict[tuple[str, str], str]:
    return {(o["method"], o["path"]): o["handler"] for o in OPERATIONS}


def test_every_endpoint_is_documented_and_nothing_extra():
    registered, documented = _registered(), _documented()
    assert set(registered) - set(documented) == set(), "endpointy bez opisu w app/openapi.py"
    assert set(documented) - set(registered) == set(), "opis endpointu, którego nie ma w aplikacji"
    # nazwa handlera w opisie (operationId) zgadza się z faktycznym handlerem
    assert {k: v for k, v in documented.items() if registered[k] != v} == {}


def test_spec_is_valid_openapi_31():
    validate(build_spec())  # rzuca wyjątek przy błędach struktury i niedziałających $ref


def test_operation_ids_are_unique_and_tags_declared():
    spec = build_spec()
    ids = [op["operationId"] for item in spec["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids)) == len(OPERATIONS)
    declared = {t["name"] for t in spec["tags"]}
    used = {tag for item in spec["paths"].values() for op in item.values() for tag in op["tags"]}
    assert used <= declared


def test_request_bodies_come_from_pydantic_models():
    spec = build_spec()
    schemas = spec["components"]["schemas"]
    body = spec["paths"]["/expenses"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/ExpenseIn"}
    props = schemas["ExpenseIn"]["properties"]
    assert set(props) >= {"category", "amount", "note", "spent_on"}
    assert schemas["ExpenseIn"]["required"] == ["category", "amount"]
    # zagnieżdżone modele (np. kredyty w budżecie) trafiają do components
    assert "LoanIn" in schemas and "CostIn" in schemas


def test_auth_and_error_responses_are_described():
    spec = build_spec()
    me = spec["paths"]["/auth/me"]["get"]
    assert me["security"] == [{"cookieAuth": []}, {"bearerAuth": []}]
    assert {"200", "401", "429"} <= set(me["responses"])
    login = spec["paths"]["/auth/login"]["post"]
    assert "security" not in login and {"200", "401", "422", "429"} <= set(login["responses"])
    delete_expense = spec["paths"]["/expenses/{expense_id}"]["delete"]
    assert {"401", "403", "404"} <= set(delete_expense["responses"])  # 403: CSRF dla zmieniających żądań
    assert delete_expense["parameters"][0]["name"] == "expense_id"
    calc = spec["paths"]["/calculate"]["post"]
    assert "security" not in calc  # kalkulator działa bez konta


def test_pagination_query_parameters_are_documented():
    params = {p["name"]: p for p in build_spec()["paths"]["/calculations"]["get"]["parameters"]}
    assert set(params) == {"limit", "cursor", "q", "type", "category", "sort"}
    assert params["limit"]["schema"]["maximum"] == 200
    assert "name_asc" in params["sort"]["schema"]["enum"]


def test_spec_and_docs_are_served_without_authentication(client):
    _, res = client.get("/api/v1/openapi.json")
    assert res.status == 200 and res.json["openapi"] == "3.1.0"
    assert res.json["info"]["title"] == "WorthMyTime API"
    assert "/auth/login" in res.json["paths"]
    _, page = client.get("/api/v1/docs")
    assert page.status == 200 and "swagger-ui" in page.text.lower()
    assert "/api/v1/openapi.json" in page.text


@pytest.mark.parametrize("path", ["/api/v1/openapi.json", "/api/v1/docs"])
def test_docs_endpoints_ignore_missing_cookies(client, path):
    assert client.get(path, headers={"Authorization": "Bearer niewazny"})[1].status == 200
