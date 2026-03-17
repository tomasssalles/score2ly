import logging
import shutil
from pathlib import Path

import cv2
import img2pdf
import numpy as np
from pdf2image import convert_from_path

from score2ly import image_processing, metadata, pdf
from score2ly.settings import ConvertSettings
from score2ly.utils import relative

logger = logging.getLogger(__name__)


def run(input_path: Path | None, output_dir: Path, settings: ConvertSettings | None = None) -> None:
    if settings is None:
        settings = ConvertSettings()
    _stage_1(input_path, output_dir)
    _stage_2(output_dir, settings)


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


def _stage_2(output_dir: Path, settings: ConvertSettings) -> None:
    existing = metadata.get_stage(output_dir, 2)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 2: already complete, skipping.")
            return

    stage1 = metadata.get_stage(output_dir, 1)
    source = output_dir / stage1["output"]
    dest = output_dir / "02.preprocessed.pdf"

    pdf_kind_msg: str
    skip_processing: bool

    if not settings.preprocess_images:
        pdf_kind_msg = "image preprocessing disabled"
        skip_processing = True
    elif settings.pdf_kind == "vector":
        pdf_kind_msg = "vector PDF"
        skip_processing = True
    elif settings.pdf_kind == "scan":
        pdf_kind_msg = "scan PDF"
        skip_processing = False
    elif pdf.is_vector(source):
        pdf_kind_msg = "vector PDF detected"
        skip_processing = True
    else:
        pdf_kind_msg = "scan detected"
        skip_processing = False

    if skip_processing:
        logger.info("Stage 2: %s, skipping crop/deskew.", pdf_kind_msg)
        shutil.copy2(source, dest)
    else:
        logger.info("Stage 2: %s, running crop/deskew.", pdf_kind_msg)
        _preprocess_scan(source, dest, settings, output_dir / "img_processing_debug")

    metadata.update_stage(output_dir, 2, {
        "description": "Crop margins and deskew pages for improved OMR accuracy",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 2: Done.")


def _preprocess_scan(source: Path, dest: Path, settings: ConvertSettings, debug_dir: Path) -> None:
    logger.info("Stage 2: rasterizing pages at 300 DPI...")
    images = convert_from_path(source, dpi=300)
    logger.info("Stage 2: rasterized %d page(s).", len(images))

    image_bytes = []
    for i, image in enumerate(images):
        logger.info("Stage 2: preprocessing page %d/%d...", i + 1, len(images))
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)

        debug_dir_i = debug_dir / f"page_{i + 1:03d}"
        debug_dir_i.mkdir(parents=True, exist_ok=True)

        processed = image_processing.process_page(
            gray,
            sheet_method=settings.sheet_method,
            block_method=settings.block_method,
            deskew=settings.deskew,
            tight_crop=settings.tight_crop,
            clahe=settings.clahe,
            projection_k=settings.projection_k,
            projection_denoise=settings.projection_denoise,
            debug_dir=debug_dir_i,
        )

        _, buf = cv2.imencode(".png", processed)
        image_bytes.append(buf.tobytes())

    logger.info("Stage 2: reassembling pages into PDF...")
    dest.write_bytes(img2pdf.convert(image_bytes))
