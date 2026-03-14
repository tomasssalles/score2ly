import logging
import shutil
from pathlib import Path

from score2ly import metadata, pdf
from score2ly.utils import relative

logger = logging.getLogger(__name__)


def run(input_path: Path | None, output_dir: Path) -> None:
    _stage_1(input_path, output_dir)
    _stage_2(output_dir)


def _stage_1(input_path: Path | None, output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, 1)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 1: already complete, skipping.")
            return

    if input_path is None:
        raise ValueError(
            "Stage 1: No input path provided and no valid copy of original score available. Aborting pipeline..."
        )

    dest = output_dir / f"01.original{input_path.suffix}"
    shutil.copy2(input_path, dest)
    metadata.update_stage(output_dir, 1, {
        "description": "Copy original score into the .s2l bundle to make it self-contained",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 1: Done. Copied the original score %s into the .s2l bundle (%s)", input_path, dest)


def _stage_2(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, 2)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 2: already complete, skipping.")
            return

    stage1 = metadata.get_stage(output_dir, 1)
    source = output_dir / stage1["output"]
    dest = output_dir / "02.preprocessed.pdf"

    if pdf.is_vector(source):
        logger.info("Stage 2: vector PDF detected, skipping crop/deskew.")
        shutil.copy2(source, dest)
    else:
        _preprocess_scan(source, dest)

    metadata.update_stage(output_dir, 2, {
        "description": "Crop margins and deskew pages for improved OMR accuracy",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 2: Done.")


def _preprocess_scan(source: Path, dest: Path) -> None:
    # TODO: rasterize pages with pdf2image
    # TODO: deskew each page image with deskew
    # TODO: crop blank margins with Pillow
    # TODO: reassemble pages into PDF with img2pdf
    # Dummy: pass through unchanged
    shutil.copy2(source, dest)
