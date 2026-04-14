import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from score2ly.settings import DEFAULT_MAX_RETRIES
from score2ly.utils import APIKey

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".config" / "score2ly" / "config.toml"


@dataclass(slots=True, frozen=True)
class AppConfig:
    default_model: str = ""
    api_keys: dict[str, APIKey] = field(default_factory=dict)
    max_retries: int | None = None

    def get_api_key_for_model(self, model: str) -> APIKey | None:
        lmodel = model.lower()
        try:
            return self.api_keys[lmodel]
        except KeyError:
            pass

        parts = lmodel.split("/")
        if len(parts) > 1:
            provider = parts[0]
            try:
                return self.api_keys[provider]
            except KeyError:
                pass

        return None


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _to_toml_string(config: AppConfig) -> str:
    lines = ["# score2ly configuration"]

    lines.append("")
    lines.append("# Default LLM model (e.g. gemini/gemini-2.5-flash)")
    if config.default_model:
        default_model_line = f"default_model = \"{_toml_escape(config.default_model)}\""
    else:
        default_model_line = "# default_model = \"\""
    lines.append(default_model_line)

    lines.append("")
    lines.append(f"# Maximum number of instructor retries on schema validation failure (default: {DEFAULT_MAX_RETRIES})")
    if config.max_retries is not None:
        max_retries_line = f"max_retries = {config.max_retries}"
    else:
        max_retries_line = f"# max_retries = {DEFAULT_MAX_RETRIES}"
    lines.append(max_retries_line)

    lines.append("")
    lines.append("# API keys per provider or model")
    if config.api_keys:
        api_keys_header_line = "[api_keys]"
        api_keys_entries_lines = [f"{k} = \"{_toml_escape(v.get_secret())}\"" for k, v in config.api_keys.items()]
    else:
        api_keys_header_line = "# [api_keys]"
        api_keys_entries_lines = [
            "# gemini = \"\"",
            "# openrouter = \"\"",
            "# gemini/gemini-3.1-flash-live-preview = \"\"",
        ]
    lines.append(api_keys_header_line)
    lines.extend(api_keys_entries_lines)

    lines.append("")
    return "\n".join(lines)


def save(config: AppConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_to_toml_string(config))


def load() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        logger.warning("Failed to read config file %s: %s", CONFIG_PATH, e)
        return AppConfig()

    default_model = data.get("default_model", "")

    raw_keys = data.get("api_keys", {})
    api_keys = {}
    for k, v in raw_keys.items():
        try:
            api_key = APIKey(v)
        except TypeError as e:
            logger.warning("Invalid API key for %s: %s", k, e)
            continue

        api_keys[k.lower()] = api_key

    max_retries = None
    raw_max_retries = data.get("max_retries")
    if raw_max_retries is not None:
        if isinstance(raw_max_retries, int):
            max_retries = raw_max_retries
        else:
            logger.warning("Invalid max_retries in config (expected integer, got %s)", type(raw_max_retries).__name__)

    return AppConfig(default_model=default_model, api_keys=api_keys, max_retries=max_retries)
