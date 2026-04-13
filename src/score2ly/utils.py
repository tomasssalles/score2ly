from pathlib import Path


def relative(path: Path, base: Path) -> Path:
    return path.absolute().relative_to(base.absolute(), walk_up=True)


class APIKey:
    _nast = 10
    __slots__ = ("_value",)

    def __init__(self, key: str):
        if not isinstance(key, str):
            raise TypeError(f"'key' must be a string, got {type(key).__name__}")

        self._value = key

    def __repr__(self) -> str:
        return f"{type(self).__name__}({'*' * self._nast!r})"

    def __str__(self) -> str:
        return "*" * self._nast

    def __bool__(self) -> bool:
        return bool(self._value)

    def get_secret(self) -> str:
        return self._value
