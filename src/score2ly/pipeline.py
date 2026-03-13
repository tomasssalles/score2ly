import shutil
from pathlib import Path

from score2ly import metadata
from score2ly.utils import relative


def run(input_path: Path, output_dir: Path) -> None:
    _stage_1(input_path, output_dir)


def _stage_1(input_path: Path, output_dir: Path) -> None:
    dest = output_dir / f"01.original{input_path.suffix}"
    shutil.copy2(input_path, dest)
    metadata.update_stage(output_dir, 1, {
        "source": {
            "absolute": str(input_path.resolve()),
            "relative": str(relative(input_path, output_dir)),
        },
        "output": {
            "absolute": str(dest.resolve()),
            "relative": str(relative(dest, output_dir)),
        },
        "checksum": metadata.checksum(dest),
    })
