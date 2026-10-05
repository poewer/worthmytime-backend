from app.config import DEFAULT_JWT_SECRET, Settings


def test_default_secret_rejected():
    assert Settings(jwt_secret=DEFAULT_JWT_SECRET).production_problems()


def test_short_secret_rejected():
    assert Settings(jwt_secret="short").production_problems()


def test_strong_secret_ok():
    assert Settings(jwt_secret="x" * 40).production_problems() == []


def test_cors_list():
    s = Settings(cors_origins="https://a.pl, https://b.pl")
    assert s.cors_origin_list == ["https://a.pl", "https://b.pl"]
