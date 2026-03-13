import logging
import shutil
from pathlib import Path

from score2ly import metadata
from score2ly.utils import relative

logger = logging.getLogger(__name__)


def run(input_path: Path, output_dir: Path) -> None:
    _stage_1(input_path, output_dir)


def _stage_1(input_path: Path, output_dir: Path) -> None:
    dest = output_dir / f"01.original{input_path.suffix}"

    existing = metadata.get_stage(output_dir, 1)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 1: already complete, skipping.")
            return

    shutil.copy2(input_path, dest)
    metadata.update_stage(output_dir, 1, {
        "description": "Copy original score into the .s2l bundle to make it self-contained",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 1: Done. Copied the original score %s into the .s2l bundle (%s)", input_path, dest)
