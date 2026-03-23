import json
import logging
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from pdf2image import convert_from_path
from pypdf import PdfReader
from PIL import Image

from score2ly import audiveris, image_processing, metadata, musicxml_cleanup, omr_layout, pdf
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
        _StageParams(
            stage=Stage.PREPROCESS,
            description="Rasterize PDF pages to grayscale PNGs, with optional targeted processing for OMR",
            output_dir_name="pages",
            dependencies=(Stage.ORIGINAL,),
            fn=_preprocess,
        ),
        _StageParams(
            stage=Stage.OMR,
            description="OMR transcription via Audiveris, one .omr project per page",
            output_dir_name="audiveris_omr",
            dependencies=(Stage.PREPROCESS,),
            fn=_omr,
        ),
        _StageParams(
            stage=Stage.MUSICXML,
            description="Export MusicXML from Audiveris .omr projects, one per page",
            output_dir_name="musicxml",
            dependencies=(Stage.OMR,),
            fn=_export_musicxml,
        ),
        _StageParams(
            stage=Stage.CLEAN_XML,
            description="Strip layout and style noise from MusicXML, keeping only musical content",
            output_dir_name="musicxml_clean",
            dependencies=(Stage.MUSICXML,),
            fn=_clean_musicxml,
        ),
        _StageParams(
            stage=Stage.LAYOUT,
            description="Extract system and measure layout from Audiveris .omr projects",
            output_dir_name="layout",
            dependencies=(Stage.OMR,),
            fn=_extract_layout,
        ),
        _StageParams(
            stage=Stage.IMAGES,
            description="Crop system and measure images from preprocessed page PNGs",
            output_dir_name="images",
            dependencies=(Stage.PREPROCESS, Stage.LAYOUT),
            fn=_crop_images,
        ),
    )

    for stage_idx, params in enumerate(stages, start=1):
        _run_stage(params, input_path, output_dir, settings, stage_idx)


class _StageFn(Protocol):
    def __call__(
        self,
        stage_output_dir: Path,
        pipeline_input_path: Path | None,
        settings: ConvertSettings,
        dependencies_to_outputs: dict[Stage, Sequence[Path]],
        stage_idx: int,
    ) -> Iterable[Path]: ...


@dataclass(frozen=True, slots=True)
class _StageParams:
    stage: Stage
    description: str
    output_dir_name: str
    dependencies: Sequence[Stage]
    fn: _StageFn


def _should_run(
    stage_idx: int,
    dependencies: Sequence[Stage],
    stage_meta: dict | None,
    pipeline_output_dir: Path,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
) -> bool:
    if not stage_meta:
        logger.info("Stage %d: No metadata yet. Running.", stage_idx)
        return True

    stage_outputs: Sequence[str] | None = stage_meta.get("outputs")
    if not stage_outputs:
        logger.info("Stage %d: No outputs in metadata. Running.", stage_idx)
        return True

    for out in stage_outputs:
        if not (pipeline_output_dir / out).exists():
            logger.info("Stage %d: Missing expected output file %s. Running.", stage_idx, out)
            return True

    source_checksums: dict[str, str] | None = stage_meta.get("source_checksums")
    if dependencies and (not source_checksums):
        logger.info("Stage %d: Stage has dependencies but no source checksums in metadata. Running.", stage_idx)
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
            stage_idx,
        )
        return True

    for src, cs in source_checksums.items():
        src_p = pipeline_output_dir / src
        if metadata.checksum(src_p) != cs:
            logger.info("Stage %d: Dependency %s has been externally modified. Running.", stage_idx, src)
            return True

    logger.info("Stage %d: Already done. Skipping.", stage_idx)
    return False


def _run_stage(
    params: _StageParams,
    pipeline_input_path: Path | None,
    pipeline_output_dir: Path,
    settings: ConvertSettings,
    stage_idx: int,
) -> None:
    stages_meta = metadata.get_stages(pipeline_output_dir)

    dependencies_to_outputs: dict[Stage, Sequence[Path]] = {}
    for dep in params.dependencies:
        dep_meta = stages_meta.get(dep)
        if (not dep_meta) or (not (dep_outputs := dep_meta.get("outputs"))):
            raise RuntimeError(f"Stage {stage_idx}: Dependency stage {dep.value!r} has not completed. Aborting...")
        dependencies_to_outputs[dep] = tuple(Path(s) for s in dep_outputs)

    stage_meta = stages_meta.get(params.stage)
    if not _should_run(stage_idx, params.dependencies, stage_meta, pipeline_output_dir, dependencies_to_outputs):
        return

    stage_output_dir = pipeline_output_dir / f"{stage_idx:02d}.{params.output_dir_name}"
    if stage_output_dir.exists():
        shutil.rmtree(stage_output_dir)
    stage_output_dir.mkdir(parents=True)

    source_checksums = {
        str(dep_out_rel_p): metadata.checksum(pipeline_output_dir / dep_out_rel_p)
        for dep_outputs in dependencies_to_outputs.values()
        for dep_out_rel_p in dep_outputs
    }

    stage_outputs = tuple(
        params.fn(stage_output_dir, pipeline_input_path, settings, dependencies_to_outputs, stage_idx)
    )

    metadata.update_stage(pipeline_output_dir, params.stage, {
        "description": params.description,
        "outputs": [str(relative(out, pipeline_output_dir)) for out in stage_outputs],
        "source_checksums": source_checksums,
    })
    logger.info("Stage %d: Done.", stage_idx)


def _copy_original(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    if pipeline_input_path is None:
        raise ValueError(
            f"Stage {stage_idx}: No input path provided and no valid copy of original score available."
            f" Aborting pipeline..."
        )

    dest = stage_output_dir / f"original{pipeline_input_path.suffix}"
    shutil.copy2(pipeline_input_path, dest)
    logger.info(
        "Stage %d: Copied the original score %s into the .s2l bundle (%s)", stage_idx, pipeline_input_path, dest
    )

    yield dest


def _preprocess(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    source = pipeline_output_dir / dependencies_to_outputs[Stage.ORIGINAL][0]

    run_heavy = _should_run_heavy_preprocessing(source, settings, stage_idx)

    pdf_pages = PdfReader(source).pages
    page_count = len(pdf_pages)
    logger.info("Stage %d: Rasterizing %d page(s)...", stage_idx, page_count)

    for i, pdf_page in enumerate(pdf_pages):
        dpi = pdf.page_rasterization_dpi(float(pdf_page.mediabox.width), float(pdf_page.mediabox.height))
        logger.info("Stage %d: Processing page %d/%d at %d DPI...", stage_idx, i + 1, page_count, dpi)
        image = convert_from_path(source, dpi=dpi, first_page=i + 1, last_page=i + 1)[0]
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)

        if run_heavy:
            debug_dir_i = pipeline_output_dir / f"img_processing_debug/page_{i + 1:03d}"
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

        page_path = stage_output_dir / f"page_{i + 1:04d}.png"
        cv2.imwrite(str(page_path), gray)
        yield page_path


def _should_run_heavy_preprocessing(source: Path, settings: ConvertSettings, stage_idx: int) -> bool:
    if settings.preprocessing_is_noop():
        logger.info("Stage %d: No preprocessing operations enabled, skipping.", stage_idx)
        return False
    if settings.pdf_kind == "vector":
        logger.info("Stage %d: Vector PDF, skipping heavy preprocessing.", stage_idx)
        return False
    if settings.pdf_kind == "scan":
        logger.info("Stage %d: Scan PDF, running heavy preprocessing.", stage_idx)
        return True
    if pdf.is_vector(source):
        logger.info("Stage %d: Vector PDF detected, skipping heavy preprocessing.", stage_idx)
        return False
    logger.info("Stage %d: Scan detected, running heavy preprocessing.", stage_idx)
    return True


def _omr(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    page_paths = sorted(
        pipeline_output_dir / p for p in dependencies_to_outputs[Stage.PREPROCESS]
    )

    for i, page_path in enumerate(page_paths):
        logger.info("Stage %d: Processing page %d/%d...", stage_idx, i + 1, len(page_paths))
        yield audiveris.run_omr(page_path, stage_output_dir, stage_idx)


def _export_musicxml(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    omr_paths = sorted(
        pipeline_output_dir / p for p in dependencies_to_outputs[Stage.OMR]
    )

    for i, omr_path in enumerate(omr_paths):
        logger.info("Stage %d: Processing page %d/%d...", stage_idx, i + 1, len(omr_paths))
        yield audiveris.export_xml(omr_path, stage_output_dir, stage_idx)


def _clean_musicxml(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    xml_paths = sorted(
        pipeline_output_dir / p for p in dependencies_to_outputs[Stage.MUSICXML]
    )

    for i, xml_path in enumerate(xml_paths):
        logger.info("Stage %d: Processing page %d/%d...", stage_idx, i + 1, len(xml_paths))
        dest = stage_output_dir / xml_path.with_suffix(".clean" + xml_path.suffix).name
        musicxml_cleanup.clean(xml_path, dest)
        yield dest


def _extract_layout(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    omr_paths = sorted(
        pipeline_output_dir / p for p in dependencies_to_outputs[Stage.OMR]
    )

    combined_sheets = []
    measure_offset = 0
    global_system_id = 0
    for page_num, omr_path in enumerate(omr_paths, start=1):
        result, measure_offset = omr_layout.extract(omr_path, stage_idx, initial_measure_offset=measure_offset)
        for sheet in result["sheets"]:
            sheet["sheet"] = page_num
            for system in sheet["systems"]:
                global_system_id += 1
                system["local_id"] = system.pop("id")
                system["global_id"] = global_system_id
            combined_sheets.append(sheet)

    dest = stage_output_dir / "layout.json"
    dest.write_text(json.dumps({"sheets": combined_sheets}, indent=2))
    yield dest


def _crop_images(
    stage_output_dir: Path,
    pipeline_input_path: Path | None,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent

    layout_path = pipeline_output_dir / dependencies_to_outputs[Stage.LAYOUT][0]
    layout = json.loads(layout_path.read_text())

    page_pngs = sorted(dependencies_to_outputs[Stage.PREPROCESS])

    systems_dir = stage_output_dir / "systems"
    measures_dir = stage_output_dir / "measures"
    systems_dir.mkdir()
    measures_dir.mkdir()

    for sheet in layout["sheets"]:
        sheet_num = sheet["sheet"]
        page_img = Image.open(pipeline_output_dir / page_pngs[sheet_num - 1])
        logger.info("Stage %d: Processing page %d/%d...", stage_idx, sheet_num, len(layout["sheets"]))

        for system in sheet["systems"]:
            sys_path = systems_dir / f"system_{system['global_id']:04d}.png"
            image_processing.crop_and_save(page_img, system["bounds"], sys_path)
            yield sys_path

            for measure in system["measures"]:
                meas_path = measures_dir / f"measure_{measure['global_id']:04d}.png"
                image_processing.crop_and_save(page_img, measure["bounds"], meas_path)
                yield meas_path
