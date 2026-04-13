import traceback

import pytest

from score2ly.utils import APIKey


def test_bool_false_for_empty():
    assert not APIKey("")


def test_bool_true_for_nonempty():
    assert APIKey("sk-secret")


def test_get_secret_returns_value():
    secret = "sk-secret"
    assert APIKey(secret).get_secret() == secret


def test_str_does_not_expose_secret():
    assert set(str(APIKey("sk-secret"))) == {"*"}


def test_repr_does_not_expose_secret():
    key = APIKey("sk-secret")
    r = repr(key)
    lstripped = r.removeprefix(APIKey.__name__).removeprefix("(").removeprefix("'").removeprefix("\"")
    stripped = lstripped.removesuffix(")").removesuffix("'").removesuffix("\"")
    assert stripped == str(key)


def test_type_error_on_non_string():
    i = 12345
    with pytest.raises(TypeError) as exc_info:
        # noinspection PyTypeChecker
        APIKey(i)

    assert str(i) not in str(exc_info.value)
    tb_str = "".join(traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb))
    assert str(i) not in tb_str
