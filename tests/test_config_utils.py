import logging
from pathlib import Path
from unittest.mock import patch

from score2ly.config_utils import AppConfig, load
from score2ly.utils import APIKey


# --- AppConfig.get_api_key_for_model ---

def _cfg(*pairs: tuple[str, str]) -> AppConfig:
    return AppConfig(api_keys={k: APIKey(v) for k, v in pairs})


def test_get_api_key_exact_model_match():
    cfg = _cfg(("gemini/gemini-2.5-flash", "key-exact"))
    key = cfg.get_api_key_for_model("gemini/gemini-2.5-flash")
    assert key is not None
    assert key.get_secret() == "key-exact"


def test_get_api_key_provider_fallback():
    cfg = _cfg(("gemini", "key-provider"))
    key = cfg.get_api_key_for_model("gemini/gemini-2.5-flash")
    assert key is not None
    assert key.get_secret() == "key-provider"


def test_get_api_key_exact_takes_precedence_over_provider():
    cfg = _cfg(("gemini/gemini-2.5-flash", "key-exact"), ("gemini", "key-provider"))
    key = cfg.get_api_key_for_model("gemini/gemini-2.5-flash")
    assert key is not None
    assert key.get_secret() == "key-exact"


def test_get_api_key_case_insensitive():
    cfg = _cfg(("anthropic", "key-anth"))
    key = cfg.get_api_key_for_model("Anthropic/claude-opus-4-6")
    assert key is not None
    assert key.get_secret() == "key-anth"


def test_get_api_key_no_slash_model():
    cfg = _cfg(("mymodel", "key-mine"))
    key = cfg.get_api_key_for_model("mymodel")
    assert key is not None
    assert key.get_secret() == "key-mine"


def test_get_api_key_returns_none_when_missing():
    cfg = _cfg(("openai", "key-oai"))
    assert cfg.get_api_key_for_model("gemini/gemini-2.5-flash") is None


def test_get_api_key_returns_none_for_empty_config():
    assert AppConfig().get_api_key_for_model("gemini/gemini-2.5-flash") is None


def test_get_api_key_returns_falsey_for_empty_key():
    cfg = _cfg(("gemini", ""))
    assert not cfg.get_api_key_for_model("gemini/gemini-2.5-flash")


# --- load() ---

def _load_from_toml(tmp_path: Path, content: str) -> AppConfig:
    p = tmp_path / "config.toml"
    p.write_text(content)
    with patch("score2ly.config_utils.CONFIG_PATH", p):
        return load()


def test_load_missing_file_returns_defaults(tmp_path):
    with patch("score2ly.config_utils.CONFIG_PATH", tmp_path / "nonexistent.toml"):
        cfg = load()
    assert cfg.default_model == ""
    assert cfg.api_keys == {}


def test_load_default_model(tmp_path):
    cfg = _load_from_toml(tmp_path, 'default_model = "gemini/gemini-2.5-flash"\n')
    assert cfg.default_model == "gemini/gemini-2.5-flash"


def test_load_api_keys(tmp_path):
    cfg = _load_from_toml(tmp_path, '[api_keys]\ngemini = "key-g"\nanthropic = "key-a"\n')
    assert cfg.api_keys["gemini"].get_secret() == "key-g"
    assert cfg.api_keys["anthropic"].get_secret() == "key-a"


def test_load_keys_lowercased(tmp_path):
    cfg = _load_from_toml(tmp_path, '[api_keys]\nGemini = "key-g"\n')
    assert cfg.api_keys["gemini"].get_secret() == "key-g"
    assert "Gemini" not in cfg.api_keys


def test_load_invalid_toml_returns_defaults(tmp_path):
    cfg = _load_from_toml(tmp_path, "this is not valid toml ][")
    assert cfg.default_model == ""
    assert cfg.api_keys == {}


def test_load_bad_api_key_entry_skipped(tmp_path):
    cfg = _load_from_toml(tmp_path, '[api_keys]\ngemini = "key-g"\nbad = 123\nopenai = "key-o"\n')
    assert cfg.api_keys["gemini"].get_secret() == "key-g"
    assert cfg.api_keys["openai"].get_secret() == "key-o"
    assert "bad" not in cfg.api_keys


def test_load_invalid_toml_no_key_leak(tmp_path, caplog):
    secret = "sk-super-secret-key"
    content = f'[api_keys]\ngemini = "{secret}"\nBROKEN SYNTAX ][\n'
    with caplog.at_level(logging.DEBUG):
        _load_from_toml(tmp_path, content)
    assert secret not in caplog.text


def test_load_bad_api_key_type_no_key_leak(tmp_path, caplog):
    secret = "sk-super-secret-key"
    bad_secret = "12345"  # used without surrounding quotes, thus parsed as an integer
    content = f'[api_keys]\ngemini = "{secret}"\nbad = {bad_secret}\n'
    with caplog.at_level(logging.DEBUG):
        _load_from_toml(tmp_path, content)
    assert secret not in caplog.text
    assert bad_secret not in caplog.text


def test_load_max_retries(tmp_path):
    cfg = _load_from_toml(tmp_path, "max_retries = 5\n")
    assert cfg.max_retries == 5


def test_load_max_retries_missing(tmp_path):
    cfg = _load_from_toml(tmp_path, 'default_model = "gemini/gemini-2.5-flash"\n')
    assert cfg.max_retries is None


def test_load_max_retries_invalid_type_ignored(tmp_path):
    cfg = _load_from_toml(tmp_path, 'max_retries = "five"\n')
    assert cfg.max_retries is None


def test_load_full_config(tmp_path, caplog):
    ant_secret = "sk-ant-123"
    gem_secret = "AIza456"
    toml = (
        f'default_model = "anthropic/claude-opus-4-6"\n'
        f'max_retries = 3\n'
        f'\n'
        f'[api_keys]\n'
        f'anthropic = "{ant_secret}"\n'
        f'gemini = "{gem_secret}"\n'
    )
    with caplog.at_level(logging.DEBUG):
        cfg = _load_from_toml(tmp_path, toml)
    assert cfg.default_model == "anthropic/claude-opus-4-6"
    assert cfg.max_retries == 3
    assert cfg.api_keys["anthropic"].get_secret() == ant_secret
    assert cfg.api_keys["gemini"].get_secret() == gem_secret
    assert ant_secret not in caplog.text
    assert gem_secret not in caplog.text
