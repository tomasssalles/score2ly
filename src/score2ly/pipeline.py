import json
import logging
import shutil
from pathlib import Path

import cv2
import img2pdf
import numpy as np
from pdf2image import convert_from_path

from score2ly import audiveris, image_processing, metadata, omr_layout, pdf
from score2ly.settings import ConvertSettings
from score2ly.utils import relative

logger = logging.getLogger(__name__)


def run(input_path: Path | None, output_dir: Path, settings: ConvertSettings | None = None) -> None:
    if settings is None:
        settings = ConvertSettings()
    _stage_1(input_path, output_dir)
    _stage_2(output_dir, settings)
    _stage_3(output_dir)
    _stage_4(output_dir)
    _stage_5(output_dir)
    _stage_6(output_dir)
    _stage_7(output_dir)


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

    run_preprocessing: bool
    if not settings.preprocess_images:
        logger.info("Stage 2: image preprocessing disabled, symlinking original.")
        run_preprocessing = False
    elif settings.pdf_kind == "vector":
        logger.info("Stage 2: vector PDF, symlinking original.")
        run_preprocessing = False
    elif settings.pdf_kind == "scan":
        logger.info("Stage 2: scan PDF, running preprocessing.")
        run_preprocessing = True
    elif pdf.is_vector(source):
        logger.info("Stage 2: vector PDF detected, symlinking original.")
        run_preprocessing = False
    else:
        logger.info("Stage 2: scan detected, running preprocessing.")
        run_preprocessing = True

    if not run_preprocessing:
        dest.symlink_to(source.relative_to(dest.parent, walk_up=True))
    else:
        if settings.preprocessing_is_noop():
            raise ValueError(
                "Image preprocessing is enabled but all steps are disabled. "
                "Enable at least one step (e.g. --deskew, --clahe, --sheet-method, --block-method)."
            )
        _preprocess_scan(source, dest, settings, output_dir / "img_processing_debug")

    metadata.update_stage(output_dir, 2, {
        "description": "Preprocess PDF pages for improved OMR accuracy",
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

        _, buf = cv2.imencode(".png", gray)
        image_bytes.append(buf.tobytes())

    logger.info("Stage 2: reassembling pages into PDF...")
    dest.write_bytes(img2pdf.convert(image_bytes))


def _stage_3(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, 3)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 3: already complete, skipping.")
            return

    stage2 = metadata.get_stage(output_dir, 2)
    source = output_dir / stage2["output"]

    work_dir = output_dir / "03.omr_work"
    omr_output = audiveris.run_omr(source, work_dir)

    dest = output_dir / "03.audiveris-project.omr"
    dest.symlink_to(omr_output.relative_to(dest.parent, walk_up=True))

    metadata.update_stage(output_dir, 3, {
        "description": "OMR transcription via Audiveris",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 3: Done.")


def _stage_4(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, 4)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 4: already complete, skipping.")
            return

    stage3 = metadata.get_stage(output_dir, 3)
    source = output_dir / stage3["output"]

    work_dir = output_dir / "04.export_work"
    xml_output = audiveris.export_xml(source, work_dir)

    dest = output_dir / "04.musicxml.xml"
    dest.symlink_to(xml_output.relative_to(dest.parent, walk_up=True))

    metadata.update_stage(output_dir, 4, {
        "description": "Export MusicXML from Audiveris .omr project",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 4: Done.")


def _stage_5(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, 5)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage 5: already complete, skipping.")
            return

    stage3 = metadata.get_stage(output_dir, 3)
    source = output_dir / stage3["output"]

    dest = output_dir / "05.omr_layout.json"
    layout = omr_layout.extract(source)
    dest.write_text(json.dumps(layout, indent=2))

    metadata.update_stage(output_dir, 5, {
        "description": "Extract system and measure layout from Audiveris .omr project",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage 5: Done.")


def _stage_6(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, 6)
    if existing is not None:
        checksums = existing.get("checksums", {})
        if checksums and all(
            (output_dir / p).exists() and metadata.checksum(output_dir / p) == c
            for p, c in checksums.items()
        ):
            logger.info("Stage 6: already complete, skipping.")
            return

    stage2 = metadata.get_stage(output_dir, 2)
    pdf_path = output_dir / stage2["output"]

    stage5 = metadata.get_stage(output_dir, 5)
    layout = json.loads((output_dir / stage5["output"]).read_text())

    images_dir = output_dir / "06.images"
    systems_dir = images_dir / "systems"
    measures_dir = images_dir / "measures"
    systems_dir.mkdir(parents=True, exist_ok=True)
    measures_dir.mkdir(parents=True, exist_ok=True)

    checksums = {}
    global_system_id = 0

    for sheet in layout["sheets"]:
        sheet_num = sheet["sheet"]
        page_w, page_h = sheet["width"], sheet["height"]
        logger.info("Stage 6: rasterizing page %d...", sheet_num)
        page_img = convert_from_path(pdf_path, size=(page_w, page_h), first_page=sheet_num, last_page=sheet_num)[0]

        for system in sheet["systems"]:
            global_system_id += 1
            sys_path = systems_dir / f"system_{global_system_id:04d}.png"
            _crop_and_save(page_img, system["bounds"], sys_path)
            checksums[str(relative(sys_path, output_dir))] = metadata.checksum(sys_path)

            for measure in system["measures"]:
                meas_path = measures_dir / f"measure_{measure['global_id']:04d}.png"
                _crop_and_save(page_img, measure["bounds"], meas_path)
                checksums[str(relative(meas_path, output_dir))] = metadata.checksum(meas_path)

    metadata.update_stage(output_dir, 6, {
        "description": "Crop system and measure images from preprocessed PDF",
        "output": str(relative(images_dir, output_dir)),
        "checksums": checksums,
    })
    logger.info("Stage 6: Done.")


_CROP_PADDING = 0.02


def _stage_7(output_dir: Path) -> None:
    logger.info("Stage 7: not yet implemented, skipping.")


def _crop_and_save(img, bounds: dict, dest: Path) -> None:
    pad = round(img.width * _CROP_PADDING)
    x = max(0, bounds["x"] - pad)
    y = max(0, bounds["y"] - pad)
    right = min(img.width, bounds["x"] + bounds["width"] + pad)
    bottom = min(img.height, bounds["y"] + bounds["height"] + pad)
    img.crop((x, y, right, bottom)).save(dest)