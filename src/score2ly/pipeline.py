import logging
import shutil
from pathlib import Path

import cv2
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
    _stage_3(output_dir)


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
        dest_dir = output_dir / existing["output"]
        checksums = existing.get("checksums", {})
        if dest_dir.is_dir() and all(
            (dest_dir / name).exists() and metadata.checksum(dest_dir / name) == chk
            for name, chk in checksums.items()
        ):
            logger.info("Stage 2: already complete, skipping.")
            return

    stage1 = metadata.get_stage(output_dir, 1)
    source = output_dir / stage1["output"]
    dest_dir = output_dir / "02.preprocessed"
    dest_dir.mkdir(exist_ok=True)

    run_preprocessing: bool
    if not settings.preprocess_images:
        logger.info("Stage 2: image preprocessing disabled, rasterizing only.")
        run_preprocessing = False
    elif settings.pdf_kind == "vector":
        logger.info("Stage 2: vector PDF, rasterizing only.")
        run_preprocessing = False
    elif settings.pdf_kind == "scan":
        logger.info("Stage 2: scan PDF, running preprocessing.")
        run_preprocessing = True
    elif pdf.is_vector(source):
        logger.info("Stage 2: vector PDF detected, rasterizing only.")
        run_preprocessing = False
    else:
        logger.info("Stage 2: scan detected, running preprocessing.")
        run_preprocessing = True

    if run_preprocessing and settings.preprocessing_is_noop():
        raise ValueError(
            "Image preprocessing is enabled but all steps are disabled. "
            "Enable at least one step (e.g. --deskew, --clahe, --sheet-method, --block-method)."
        )

    logger.info("Stage 2: rasterizing pages at 300 DPI...")
    images = convert_from_path(source, dpi=300)
    logger.info("Stage 2: rasterized %d page(s).", len(images))

    checksums = {}
    for i, image in enumerate(images):
        page_name = f"page_{i + 1:03d}.png"
        dest = dest_dir / page_name
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)

        if run_preprocessing:
            logger.info("Stage 2: preprocessing page %d/%d...", i + 1, len(images))
            debug_dir_i = output_dir / "img_processing_debug" / f"page_{i + 1:03d}"
            debug_dir_i.mkdir(parents=True, exist_ok=True)
            gray = image_processing.process_page(
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

        cv2.imwrite(str(dest), gray)
        checksums[page_name] = metadata.checksum(dest)

    metadata.update_stage(output_dir, 2, {
        "description": "Rasterize PDF into per-page images and optionally preprocess them for better OMR accuracy",
        "output": str(relative(dest_dir, output_dir)),
        "checksums": checksums,
    })
    logger.info("Stage 2: Done.")


def _stage_3(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, 3)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 3: already complete, skipping.")
            return

    dest = output_dir / "03.omr_extracted.xml"
    placeholder = Path(__file__).parent / "placeholder_musicxml.xml"
    shutil.copy2(placeholder, dest)

    metadata.update_stage(output_dir, 3, {
        "description": "OMR extraction from preprocessed pages to MusicXML (placeholder)",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 3: Done (placeholder).")
