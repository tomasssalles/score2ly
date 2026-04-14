import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

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
