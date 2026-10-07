# ruff: noqa: F811
from sanic_testing.reusable import ReusableClient

from app.config import settings
from app.main import create_app
from tests.test_api import PROFILE, _free_port, client  # noqa: F401

PASSWORD = "supersecret1"


def _register(client, email):
    """Rejestruje konto i zwraca odpowiedź oraz jej cookie; czyści słoik klienta, żeby testy wysyłały cookie jawnie."""
    _, res = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    cookies = dict(res.cookies.items())
    client._session.cookies.clear()
    return res, cookies


def _flags(res, name: str) -> str:
    return next(h.lower() for h in res.headers.get_list("set-cookie") if h.startswith(f"{name}="))


def test_login_sets_httponly_session_cookie_and_readable_csrf_cookie(client):
    res, cookies = _register(client, "ck@b.pl")
    assert res.status == 201 and res.json["token"]  # token w treści nadal dla klientów API
    session, csrf = _flags(res, "wmt_session"), _flags(res, "wmt_csrf")
    assert "httponly" in session and "samesite=lax" in session and "path=/" in session and "max-age=" in session
    assert "httponly" not in csrf  # JS musi odczytać token CSRF
    assert "samesite=lax" in csrf
    assert {"wmt_session", "wmt_csrf"} <= set(cookies)


def test_login_endpoint_sets_cookies_too(client):
    _register(client, "ck1@b.pl")
    _, res = client.post("/api/v1/auth/login", json={"email": "ck1@b.pl", "password": PASSWORD})
    assert res.status == 200 and "httponly" in _flags(res, "wmt_session")


def test_cookie_session_authenticates_reads_without_csrf(client):
    _, cookies = _register(client, "ck2@b.pl")
    _, me = client.get("/api/v1/auth/me", cookies={"wmt_session": cookies["wmt_session"]})
    assert me.status == 200 and me.json["email"] == "ck2@b.pl"
    assert client.get("/api/v1/auth/me", cookies={"wmt_session": "zly-token"})[1].status == 401
    assert client.get("/api/v1/auth/me")[1].status == 401


def test_cookie_authenticated_writes_require_matching_csrf_token(client):
    _, cookies = _register(client, "ck3@b.pl")
    only_session = {"wmt_session": cookies["wmt_session"]}

    def put(headers=None, cookie=cookies):
        client._session.cookies.clear()
        return client.put("/api/v1/profile", json=PROFILE, cookies=cookie, headers=headers or {})[1]

    assert put().status == 403  # brak nagłówka
    assert put({"X-CSRF-Token": "inny"}).status == 403  # inna wartość niż w cookie
    assert put({"X-CSRF-Token": cookies["wmt_csrf"]}, only_session).status == 403  # brak cookie csrf
    assert put({"X-CSRF-Token": cookies["wmt_csrf"]}).status == 200


def test_bearer_header_does_not_need_csrf(client):
    res, _ = _register(client, "ck4@b.pl")
    auth = {"Authorization": f"Bearer {res.json['token']}"}
    assert client.put("/api/v1/profile", json=PROFILE, headers=auth)[1].status == 200


def test_anonymous_requests_do_not_need_csrf(client):
    _, cookies = _register(client, "ck5@b.pl")
    # przeglądarka z cookie sesji nadal liczy anonimowo (bez uwierzytelnienia) bez tokenu CSRF
    _, calc = client.post(
        "/api/v1/calculate",
        json={"calculation": {"name": "x", "purchase_price": 100}, "profile": {"monthly_income": 5000}},
        cookies=cookies,
    )
    assert calc.status == 200


def test_logout_clears_cookies_and_is_idempotent(client):
    _, cookies = _register(client, "ck6@b.pl")
    _, out = client.post("/api/v1/auth/logout", cookies=cookies)
    assert out.status == 200 and out.json["logged_out"] is True
    cleared = [h.lower() for h in out.headers.get_list("set-cookie")]
    assert any(h.startswith("wmt_session=") and ("max-age=0" in h or "1970" in h) for h in cleared)
    assert any(h.startswith("wmt_csrf=") and ("max-age=0" in h or "1970" in h) for h in cleared)
    client._session.cookies.clear()
    assert client.post("/api/v1/auth/logout")[1].status == 200  # bez sesji też działa


def test_session_exchange_turns_bearer_token_into_cookies(client):
    res, _ = _register(client, "ck7@b.pl")
    token = res.json["token"]
    assert client.post("/api/v1/auth/session")[1].status == 401
    assert client.post("/api/v1/auth/session", headers={"Authorization": "Bearer zly"})[1].status == 401
    _, ex = client.post("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert ex.status == 200 and {"wmt_session", "wmt_csrf"} <= set(dict(ex.cookies.items()))
    assert "httponly" in _flags(ex, "wmt_session")


def test_cors_allows_credentials_only_for_listed_origins(client):
    headers = {"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    _, ok = client.options("/api/v1/auth/me", headers=headers)
    # w testach CORS_ORIGINS=* (domyślnie): bez credentials, bo przeglądarka odrzuca * z cookie
    assert ok.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in ok.headers
    assert "x-csrf-token" in ok.headers["access-control-allow-headers"].lower()


def test_cors_with_explicit_origin_sends_credentials_and_rejects_others(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "https://app.example.com")
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'cors.db'}", create_schema=True)
    with ReusableClient(app, port=_free_port()) as c:
        _, res = c.options("/api/v1/auth/me", headers={"Origin": "https://app.example.com"})
        assert res.headers["access-control-allow-origin"] == "https://app.example.com"
        assert res.headers["access-control-allow-credentials"] == "true"
        assert res.headers["vary"] == "Origin"
        _, other = c.options("/api/v1/auth/me", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in other.headers
        assert "access-control-allow-credentials" not in other.headers


def test_production_config_rejects_samesite_none_without_secure(monkeypatch):
    monkeypatch.setattr(settings, "cookie_samesite", "none")
    monkeypatch.setattr(settings, "cookie_secure", False)
    assert any("COOKIE_SAMESITE=none" in p for p in settings.production_problems())
    monkeypatch.setattr(settings, "cookie_samesite", "ciasteczko")
    assert any("COOKIE_SAMESITE musi" in p for p in settings.production_problems())
