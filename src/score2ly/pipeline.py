import json
import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from pathlib import Path

import cv2
import numpy as np
from pdf2image import convert_from_path

from score2ly import audiveris, image_processing, lilypond, metadata, musicxml2ly, omr_layout, pdf
from score2ly.settings import ConvertSettings
from score2ly.stages import Stage
from score2ly.utils import relative

logger = logging.getLogger(__name__)


def run(input_path: Path | None, output_dir: Path, settings: ConvertSettings | None = None) -> None:
    settings = settings or ConvertSettings()

    stages: Sequence[_StageParams] = (
        _StageParams(
            stage=Stage.ORIGINAL,
            description="Copy original score into the .s2l bundle to make it self-contained",
            output_dir_name="original",
            dependencies=(),
            fn=_copy_original,
        ),
    )

    for params in stages:
        _run_stage(params, input_path, output_dir, settings)


class _StageFn(Protocol):
    def __call__(
        self,
        stage_output_dir: Path,
        pipeline_input_path: Path | None,
        settings: ConvertSettings,
        dependencies_to_outputs: dict[Stage, Sequence[Path]],
    ) -> Sequence[Path]: ...


@dataclass(frozen=True, slots=True)
class _StageParams:
    stage: Stage
    description: str
    output_dir_name: str
    dependencies: Sequence[Stage]
    fn: _StageFn


def _should_run(
    stage: Stage,
    dependencies: Sequence[Stage],
    stage_meta: dict | None,
    pipeline_output_dir: Path,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
) -> bool:
    if not stage_meta:
        logger.info("Stage %d: No metadata yet. Running.", stage)
        return True

    stage_outputs: Sequence[str] | None = stage_meta.get("outputs")
    if not stage_outputs:
        logger.info("Stage %d: No outputs in metadata. Running.", stage)
        return True

    for out in stage_outputs:
        if not (pipeline_output_dir / out).exists():
            logger.info("Stage %d: Missing expected output file %s. Running.", stage, out)
            return True

    source_checksums: dict[str, str] | None = stage_meta.get("source_checksums")
    if dependencies and (not source_checksums):
        logger.info("Stage %d: Stage has dependencies but no source checksums in metadata. Running.", stage)
        return True

    if source_checksums is None:
        source_checksums = {}

    updated_sources = {
        str(dep_out)
        for dep_outputs in dependencies_to_outputs.values()
        for dep_out in dep_outputs
    }
    if updated_sources != set(source_checksums.keys()):
        logger.info(
            "Stage %d: Dependencies listed in metadata do not match current dependencies. Running.",
            stage,
        )
        return True

    for src, cs in source_checksums.items():
        src_p = pipeline_output_dir / src
        if metadata.checksum(src_p) != cs:
            logger.info("Stage %d: Dependency %s has been externally modified. Running.", stage, src)
            return True

    logger.info("Stage %d: Already done. Skipping.", stage)
    return False


def _run_stage(
    params: _StageParams,
    pipeline_input_path: Path | None,
    pipeline_output_dir: Path,
    settings: ConvertSettings,
) -> None:
    stages_meta = metadata.get_stages(pipeline_output_dir)

    dependencies_to_outputs: dict[Stage, Sequence[Path]] = {}
    for dep in params.dependencies:
        dep_meta = stages_meta.get(dep)
        if (not dep_meta) or (not (dep_outputs := dep_meta.get("outputs"))):
            raise RuntimeError(f"Stage {params.stage}: Dependency stage {dep} has not completed. Aborting...")
        dependencies_to_outputs[dep] = tuple(Path(s) for s in dep_outputs)

    stage_meta = stages_meta.get(params.stage)
    if not _should_run(params.stage, params.dependencies, stage_meta, pipeline_output_dir, dependencies_to_outputs):
        return

    stage_output_dir = pipeline_output_dir / f"{int(params.stage):02d}.{params.output_dir_name}"
    if stage_output_dir.exists():
        shutil.rmtree(stage_output_dir)
    stage_output_dir.mkdir(parents=True)

    stage_outputs = params.fn(stage_output_dir, pipeline_input_path, settings, dependencies_to_outputs)

    source_checksums = {
        str(dep_out_rel_p): metadata.checksum(pipeline_output_dir / dep_out_rel_p)
        for dep_outputs in dependencies_to_outputs.values()
        for dep_out_rel_p in dep_outputs
    }

    metadata.update_stage(pipeline_output_dir, params.stage, {
        "description": params.description,
        "outputs": [str(relative(out, pipeline_output_dir)) for out in stage_outputs],
        "source_checksums": source_checksums,
    })
    logger.info("Stage %d: Done.", params.stage)


def _copy_original(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
) -> Sequence[Path]:
    if pipeline_input_path is None:
        raise ValueError(
            f"Stage {Stage.ORIGINAL}: No input path provided and no valid copy of original score available."
            f" Aborting pipeline..."
        )

    dest = stage_output_dir / f"original{pipeline_input_path.suffix}"
    shutil.copy2(pipeline_input_path, dest)
    logger.info(
        "Stage %d: Copied the original score %s into the .s2l bundle (%s)", Stage.ORIGINAL, pipeline_input_path, dest
    )

    return (dest,)


# -- LEGACY STAGE IMPLEMENTATIONS -- NOT IN USE -- TO BE REPLACED --

def _stage_preprocess(output_dir: Path, settings: ConvertSettings) -> None:
    existing = metadata.get_stage(output_dir, Stage.PREPROCESS)
    if existing is not None:
        checksums = existing.get("checksums", {})
        if checksums and all(
            (output_dir / p).exists() and metadata.checksum(output_dir / p) == c
            for p, c in checksums.items()
        ):
            logger.info("Stage %d: already complete, skipping.", Stage.PREPROCESS)
            return

    stage_original = metadata.get_stage(output_dir, Stage.ORIGINAL)
    source = output_dir / stage_original["output"]

    run_heavy = _should_run_heavy_preprocessing(source, settings)

    pages_dir = output_dir / f"{int(Stage.PREPROCESS):02d}.pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Stage %d: rasterizing pages at 300 DPI...", Stage.PREPROCESS)
    images = convert_from_path(source, dpi=300)
    logger.info("Stage %d: rasterized %d page(s).", Stage.PREPROCESS, len(images))

    checksums = {}
    for i, image in enumerate(images):
        logger.info("Stage %d: processing page %d/%d...", Stage.PREPROCESS, i + 1, len(images))
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)

        if run_heavy:
            debug_dir_i = output_dir / f"img_processing_debug/page_{i + 1:03d}"
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

        page_path = pages_dir / f"page_{i + 1:04d}.png"
        cv2.imwrite(str(page_path), gray)
        checksums[str(relative(page_path, output_dir))] = metadata.checksum(page_path)

    metadata.update_stage(output_dir, Stage.PREPROCESS, {
        "description": "Rasterize PDF pages to grayscale PNGs, with optional targeted processing for OMR",
        "output": str(relative(pages_dir, output_dir)),
        "checksums": checksums,
    })
    logger.info("Stage %d: Done.", Stage.PREPROCESS)


def _should_run_heavy_preprocessing(source: Path, settings: ConvertSettings) -> bool:
    if not settings.preprocess_images or settings.preprocessing_is_noop():
        logger.info("Stage %d: heavy preprocessing disabled, skipping.", Stage.PREPROCESS)
        return False
    if settings.pdf_kind == "vector":
        logger.info("Stage %d: vector PDF, skipping heavy preprocessing.", Stage.PREPROCESS)
        return False
    if settings.pdf_kind == "scan":
        logger.info("Stage %d: scan PDF, running heavy preprocessing.", Stage.PREPROCESS)
        return True
    if pdf.is_vector(source):
        logger.info("Stage %d: vector PDF detected, skipping heavy preprocessing.", Stage.PREPROCESS)
        return False
    logger.info("Stage %d: scan detected, running heavy preprocessing.", Stage.PREPROCESS)
    return True


def _stage_omr(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, Stage.OMR)
    if existing is not None:
        checksums = existing.get("checksums", {})
        if checksums and all(
            (output_dir / p).exists() and metadata.checksum(output_dir / p) == c
            for p, c in checksums.items()
        ):
            logger.info("Stage %d: already complete, skipping.", Stage.OMR)
            return

    stage_preprocess = metadata.get_stage(output_dir, Stage.PREPROCESS)
    pages_dir = output_dir / stage_preprocess["output"]
    page_paths = sorted(pages_dir.glob("*.png"))

    work_dir = output_dir / f"{int(Stage.OMR):02d}.audiveris_omr"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir()

    # update_stage is only reached if all pages succeed — a partial run leaves
    # the stage unrecorded so it will be retried in full on the next invocation
    checksums = {}
    for i, page_path in enumerate(page_paths):
        logger.info("Stage %d: processing page %d/%d...", Stage.OMR, i + 1, len(page_paths))
        omr_path = audiveris.run_omr(page_path, work_dir)
        checksums[str(relative(omr_path, output_dir))] = metadata.checksum(omr_path)

    metadata.update_stage(output_dir, Stage.OMR, {
        "description": "OMR transcription via Audiveris, one .omr project per page",
        "output": str(relative(work_dir, output_dir)),
        "checksums": checksums,
    })
    logger.info("Stage %d: Done.", Stage.OMR)


def _stage_export_musicxml(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, Stage.MUSICXML)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage %d: already complete, skipping.", Stage.MUSICXML)
            return

    stage_omr = metadata.get_stage(output_dir, Stage.OMR)
    source = output_dir / stage_omr["output"]

    work_dir = output_dir / f"{int(Stage.MUSICXML):02d}.export_work"
    xml_output = audiveris.export_xml(source, work_dir)

    dest = output_dir / f"{int(Stage.MUSICXML):02d}.musicxml.xml"
    dest.symlink_to(xml_output.relative_to(dest.parent, walk_up=True))

    metadata.update_stage(output_dir, Stage.MUSICXML, {
        "description": "Export MusicXML from Audiveris .omr project",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage %d: Done.", Stage.MUSICXML)


def _stage_extract_layout(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, Stage.LAYOUT)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage %d: already complete, skipping.", Stage.LAYOUT)
            return

    stage_omr = metadata.get_stage(output_dir, Stage.OMR)
    source = output_dir / stage_omr["output"]

    dest = output_dir / f"{int(Stage.LAYOUT):02d}.omr_layout.json"
    layout = omr_layout.extract(source)
    dest.write_text(json.dumps(layout, indent=2))

    metadata.update_stage(output_dir, Stage.LAYOUT, {
        "description": "Extract system and measure layout from Audiveris .omr project",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage %d: Done.", Stage.LAYOUT)


def _stage_crop(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, Stage.IMAGES)
    if existing is not None:
        checksums = existing.get("checksums", {})
        if checksums and all(
            (output_dir / p).exists() and metadata.checksum(output_dir / p) == c
            for p, c in checksums.items()
        ):
            logger.info("Stage %d: already complete, skipping.", Stage.IMAGES)
            return

    stage_preprocess = metadata.get_stage(output_dir, Stage.PREPROCESS)
    pdf_path = output_dir / stage_preprocess["output"]

    stage_layout = metadata.get_stage(output_dir, Stage.LAYOUT)
    layout = json.loads((output_dir / stage_layout["output"]).read_text())

    images_dir = output_dir / f"{int(Stage.IMAGES):02d}.images"
    pages_dir = images_dir / "pages"
    systems_dir = images_dir / "systems"
    measures_dir = images_dir / "measures"
    pages_dir.mkdir(parents=True, exist_ok=True)
    systems_dir.mkdir(parents=True, exist_ok=True)
    measures_dir.mkdir(parents=True, exist_ok=True)

    checksums = {}
    global_system_id = 0

    for sheet in layout["sheets"]:
        sheet_num = sheet["sheet"]
        page_w, page_h = sheet["width"], sheet["height"]
        logger.info("Stage %d: rasterizing page %d...", Stage.IMAGES, sheet_num)
        page_img = convert_from_path(pdf_path, size=(page_w, page_h), first_page=sheet_num, last_page=sheet_num)[0]

        page_path = pages_dir / f"page_{sheet_num:04d}.png"
        page_img.save(page_path)
        checksums[str(relative(page_path, output_dir))] = metadata.checksum(page_path)

        for system in sheet["systems"]:
            global_system_id += 1
            sys_path = systems_dir / f"system_{global_system_id:04d}.png"
            image_processing.crop_and_save(page_img, system["bounds"], sys_path)
            checksums[str(relative(sys_path, output_dir))] = metadata.checksum(sys_path)

            for measure in system["measures"]:
                meas_path = measures_dir / f"measure_{measure['global_id']:04d}.png"
                image_processing.crop_and_save(page_img, measure["bounds"], meas_path)
                checksums[str(relative(meas_path, output_dir))] = metadata.checksum(meas_path)

    metadata.update_stage(output_dir, Stage.IMAGES, {
        "description": "Rasterize pages and crop system and measure images from preprocessed PDF",
        "output": str(relative(images_dir, output_dir)),
        "checksums": checksums,
    })
    logger.info("Stage %d: Done.", Stage.IMAGES)


def _stage_musicxml2ly(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, Stage.LILYPOND)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage %d: already complete, skipping.", Stage.LILYPOND)
            return

    stage_musicxml = metadata.get_stage(output_dir, Stage.MUSICXML)
    source = output_dir / stage_musicxml["output"]

    dest = output_dir / f"{int(Stage.LILYPOND):02d}.lilypond.ly"
    musicxml2ly.run(source, dest)

    metadata.update_stage(output_dir, Stage.LILYPOND, {
        "description": "Convert MusicXML to LilyPond via musicxml2ly",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage %d: Done.", Stage.LILYPOND)


def _stage_render(output_dir: Path) -> None:
    existing = metadata.get_stage(output_dir, Stage.RENDER)
    if existing is not None:
        dest_existing = output_dir / existing["output"]
        if dest_existing.exists() and metadata.checksum(dest_existing) == existing["checksum"]:
            logger.info("Stage %d: already complete, skipping.", Stage.RENDER)
            return

    stage_lilypond = metadata.get_stage(output_dir, Stage.LILYPOND)
    source = output_dir / stage_lilypond["output"]

    dest = output_dir / f"{int(Stage.RENDER):02d}.rendered.pdf"
    lilypond.render(source, dest)

    metadata.update_stage(output_dir, Stage.RENDER, {
        "description": "Render LilyPond score to PDF",
        "output": str(relative(dest, output_dir)),
        "checksum": metadata.checksum(dest),
    })
    logger.info("Stage %d: Done.", Stage.RENDER)
