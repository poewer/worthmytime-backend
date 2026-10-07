import pytest

from app.errors import ApiError
from app.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, encode_cursor, escape_like, parse_list_params


def test_defaults():
    p = parse_list_params({})
    assert (p.limit, p.offset, p.q, p.type, p.category, p.sort) == (DEFAULT_LIMIT, 0, None, None, None, "created_desc")


def test_cursor_roundtrip_and_rejects_garbage():
    for offset in (0, 1, 20, 12345):
        assert decode_cursor(encode_cursor(offset)) == offset
    for bad in ("!!!", "", "bzI6NQ", encode_cursor(5)[:-2] + "@@"):
        with pytest.raises(ApiError) as e:
            decode_cursor(bad)
        assert e.value.status_code == 422


@pytest.mark.parametrize(
    "args",
    [
        {"limit": "0"},
        {"limit": str(MAX_LIMIT + 1)},
        {"limit": "abc"},
        {"sort": "cost_desc"},
        {"type": "WRONG"},
        {"category": "WRONG"},
        {"q": "x" * 101},
        {"cursor": "nie-kursor"},
    ],
)
def test_invalid_params_are_rejected(args):
    with pytest.raises(ApiError) as e:
        parse_list_params(args)
    assert e.value.status_code == 422


def test_valid_params_are_parsed_and_q_is_trimmed():
    args = {"limit": "5", "cursor": encode_cursor(10), "q": "  iphone ", "type": "TCO", "category": "FUN"}
    p = parse_list_params({**args, "sort": "name_asc"})
    assert (p.limit, p.offset, p.q, p.type, p.category, p.sort) == (5, 10, "iphone", "TCO", "FUN", "name_asc")
    assert parse_list_params({"q": "   "}).q is None


def test_escape_like_treats_wildcards_literally():
    assert escape_like("50%_off\\") == "50\\%\\_off\\\\"
