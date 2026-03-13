import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from score2ly.utils import relative

METADATA_FILENAME = "score2ly.metadata.json"


def _path(output_dir: Path) -> Path:
    return output_dir / METADATA_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checksum(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def _load(output_dir: Path) -> dict:
    return json.loads(_path(output_dir).read_text())


def _save(output_dir: Path, data: dict) -> None:
    _path(output_dir).write_text(json.dumps(data, indent=2))


def create(output_dir: Path, argv: list[str], working_dir: Path, input_path: Path) -> None:
    data = {
        "command": argv,
        "working_directory": str(working_dir),
        "input": {
            "absolute": str(input_path.resolve()),
            "relative": str(relative(input_path, output_dir)),
        },
        "history": [{"event": "created", "timestamp": _now()}],
        "stages": {},
    }
    _save(output_dir, data)


def append_history(output_dir: Path, event: str) -> None:
    data = _load(output_dir)
    data["history"].append({"event": event, "timestamp": _now()})
    _save(output_dir, data)


def update_stage(output_dir: Path, stage: int, stage_data: dict) -> None:
    data = _load(output_dir)
    data["stages"][str(stage)] = stage_data
    data["history"].append({"event": f"stage-{stage}-completed", "timestamp": _now()})
    _save(output_dir, data)
