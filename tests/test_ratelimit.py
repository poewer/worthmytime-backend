import socket

import pytest
from sanic_testing.reusable import ReusableClient

from app.main import create_app
from app.ratelimit import Limits, RateLimiter, SlidingWindow


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_sliding_window_blocks_and_releases():
    clock = Clock()
    w = SlidingWindow(limit=3, window=60, clock=clock)
    assert [w.hit("a") for _ in range(3)] == [0, 0, 0]
    wait = w.hit("a")
    assert 1 <= wait <= 61
    assert w.hit("b") == 0  # inny klucz ma wĹ‚asny licznik
    clock.now += 61
    assert w.hit("a") == 0  # okno minÄ™Ĺ‚o


def test_blocked_hit_does_not_extend_the_block():
    clock = Clock()
    w = SlidingWindow(limit=1, window=10, clock=clock)
    w.hit("a")
    clock.now += 5
    assert w.hit("a") > 0
    clock.now += 6  # od pierwszego zdarzenia minÄ™Ĺ‚o 11 s
    assert w.hit("a") == 0


def test_login_lockout_per_account_and_ip():
    clock = Clock()
    rl = RateLimiter(Limits(login_max_failures=3, login_window_seconds=900), clock)
    for _ in range(3):
        assert rl.login_blocked("1.1.1.1", "A@b.pl") == 0
        rl.login_failed("1.1.1.1", "a@b.pl")  # wielkoĹ›Ä‡ liter e-maila nie ma znaczenia
    assert rl.login_blocked("1.1.1.1", "a@b.pl") > 0
    assert rl.login_blocked("2.2.2.2", "a@b.pl") == 0  # inny adres nie jest blokowany
    assert rl.login_blocked("1.1.1.1", "inne@b.pl") == 0
    clock.now += 901
    assert rl.login_blocked("1.1.1.1", "a@b.pl") == 0


def test_successful_login_clears_failures():
    rl = RateLimiter(Limits(login_max_failures=3))
    rl.login_failed("1.1.1.1", "a@b.pl")
    rl.login_failed("1.1.1.1", "a@b.pl")
    rl.login_succeeded("1.1.1.1", "a@b.pl")
    rl.login_failed("1.1.1.1", "a@b.pl")
    assert rl.login_blocked("1.1.1.1", "a@b.pl") == 0


def test_disabled_limiter_never_blocks():
    rl = RateLimiter(Limits(enabled=False, login_max_failures=1, api_per_minute=1, auth_per_minute=1))
    for _ in range(5):
        rl.login_failed("1.1.1.1", "a@b.pl")
        assert rl.check_api("1.1.1.1") == 0
        assert rl.check_auth("1.1.1.1") == 0
    assert rl.login_blocked("1.1.1.1", "a@b.pl") == 0


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def limited_client(tmp_path):
    limits = Limits(api_per_minute=40, auth_per_minute=30, login_max_failures=3, login_window_seconds=900)
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'rl.db'}", create_schema=True, limits=limits)
    with ReusableClient(app, port=_free_port()) as c:
        yield c


def test_login_is_locked_after_repeated_failures(limited_client):
    c = limited_client
    c.post("/api/v1/auth/register", json={"email": "rl@b.pl", "password": "supersecret1"})
    bad = {"email": "rl@b.pl", "password": "zlehaslo123"}
    assert [c.post("/api/v1/auth/login", json=bad)[1].status for _ in range(3)] == [401, 401, 401]
    _, res = c.post("/api/v1/auth/login", json=bad)
    assert res.status == 429
    assert int(res.headers["retry-after"]) > 0
    assert "nieudanych" in res.json["error"]
    # nawet poprawne hasĹ‚o jest wstrzymane na czas blokady
    _, res = c.post("/api/v1/auth/login", json={"email": "rl@b.pl", "password": "supersecret1"})
    assert res.status == 429
    # inne konto z tego samego adresu loguje siÄ™ normalnie
    c.post("/api/v1/auth/register", json={"email": "ok@b.pl", "password": "supersecret1"})
    _, res = c.post("/api/v1/auth/login", json={"email": "ok@b.pl", "password": "supersecret1"})
    assert res.status == 200


def test_api_rate_limit_returns_429_but_health_is_exempt(limited_client):
    c = limited_client
    statuses = [c.get("/api/v1/auth/me")[1].status for _ in range(45)]
    assert statuses[:40] == [401] * 40
    assert statuses[40:] == [429] * 5
    _, res = c.get("/api/v1/auth/me")
    assert res.status == 429 and "retry-after" in res.headers
    assert c.get("/api/v1/health")[1].status == 200  # monitoring nie jest limitowany


def test_rate_limit_is_off_in_default_test_app(tmp_path):
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'x.db'}", create_schema=True)
    assert app.ctx.limiter.limits.enabled is False

