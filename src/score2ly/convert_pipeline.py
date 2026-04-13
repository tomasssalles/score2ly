import json
import logging
import shutil
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path

import cv2
import numpy as np
from pdf2image import convert_from_path
from pypdf import PdfReader, PdfWriter
from PIL import Image

from score2ly import (
    audiveris,
    image_processing,
    lilypond,
    ly_merge,
    metadata,
    musicxml_cleanup,
    musicxml_snippets,
    musicxml2ly,
    omr_layout,
    pdf,
    score_info,
)
from score2ly.exceptions import PipelineError
from score2ly.pdf import PdfKind
from score2ly.pipeline_common import StageParams, run_stage
from score2ly.settings import ConvertSettings
from score2ly.stages import Stage
from score2ly.utils import relative

logger = logging.getLogger(__name__)


# noinspection PyTypeChecker
def get_stage_params(input_pdf_path: Path | None, input_xml_path: Path | None) -> Sequence[StageParams[ConvertSettings]]:
    return (
        StageParams(
            stage=Stage.ORIGINAL,
            description="Copy original score into the .s2l bundle",
            output_dir_name="original",
            dependencies=(),
            fn=lambda *a, **kw: _copy_original(input_pdf_path, *a, **kw),
        ),
        StageParams(
            stage=Stage.PREPROCESS,
            description="Rasterize PDF pages, with optional processing for OMR",
            output_dir_name="pages",
            dependencies=(Stage.ORIGINAL,),
            fn=_preprocess,
        ),
        StageParams(
            stage=Stage.OMR,
            description="Run Audiveris OMR for layout coordinates and MusicXML extraction",
            output_dir_name="audiveris_omr",
            dependencies=(Stage.PREPROCESS,),
            fn=_omr,
        ),
        StageParams(
            stage=Stage.MUSICXML,
            description="Export MusicXML from the Audiveris .omr project",
            output_dir_name="musicxml",
            dependencies=(Stage.OMR,),
            fn=lambda *a, **kw: _export_musicxml(input_xml_path, *a, **kw),
        ),
        StageParams(
            stage=Stage.CLEAN_XML,
            description="Strip layout and style noise from MusicXML",
            output_dir_name="musicxml_clean",
            dependencies=(Stage.MUSICXML,),
            fn=_clean_musicxml,
        ),
        StageParams(
            stage=Stage.SCORE_INFO,
            description="Collect score-header information",
            output_dir_name="score_info",
            dependencies=(Stage.MUSICXML,),
            fn=_collect_score_info,
        ),
        StageParams(
            stage=Stage.LILYPOND,
            description="Convert clean MusicXML to LilyPond",
            output_dir_name="lilypond",
            dependencies=(Stage.CLEAN_XML, Stage.SCORE_INFO),
            fn=_merge_ly,
        ),
        StageParams(
            stage=Stage.LY_RENDER,
            description="Render LilyPond score to PDF",
            output_dir_name="ly_render",
            dependencies=(Stage.LILYPOND,),
            fn=_render_ly,
        ),
        StageParams(
            stage=Stage.LAYOUT,
            description="Extract system and measure layout from Audiveris .omr projects",
            output_dir_name="layout",
            dependencies=(Stage.OMR,),
            fn=_extract_layout,
        ),
        StageParams(
            stage=Stage.IMAGES,
            description="Crop system and measure images from page PNGs",
            output_dir_name="images",
            dependencies=(Stage.PREPROCESS, Stage.LAYOUT),
            fn=_crop_images,
        ),
        StageParams(
            stage=Stage.XML_SNIPPETS,
            description="Extract per-system and per-measure MusicXML snippets",
            output_dir_name="xml_snippets",
            dependencies=(Stage.CLEAN_XML, Stage.LAYOUT),
            fn=_extract_xml_snippets,
        ),
        StageParams(
            stage=Stage.LY_SNIPPETS,
            description="Convert MusicXML snippets to LilyPond",
            output_dir_name="ly_snippets",
            dependencies=(Stage.XML_SNIPPETS,),
            fn=_convert_ly_snippets,
        ),
    )


def run(input_pdf_path: Path | None, input_xml_path: Path | None, output_dir: Path, settings: ConvertSettings) -> None:
    if input_xml_path is not None:
        for out in metadata.get_stages(output_dir).get(Stage.MUSICXML, {}).get("outputs", []):
            (output_dir / out).unlink(missing_ok=True)

    for stage_idx, params in enumerate(get_stage_params(input_pdf_path, input_xml_path), start=1):
        run_stage(params, output_dir, settings, stage_idx, logger)

    logger.info("Conversion pipeline finished successfully.")


def _copy_original(
    pipeline_input_path: Path | None,
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    if pipeline_input_path is None:
        raise PipelineError(
            f"Stage {stage_idx}: No input path provided and no valid copy of original score available."
            f" Aborting pipeline..."
        )

    if settings.page_range is not None:
        start, end = settings.page_range
        reader = PdfReader(pipeline_input_path)
        total = len(reader.pages)
        if end > total:
            raise PipelineError(
                f"Stage {stage_idx}: Page range {start}-{end} exceeds PDF page count ({total})."
            )
        writer = PdfWriter()
        for i in range(start - 1, end):
            writer.add_page(reader.pages[i])

        dest = stage_output_dir / f"original.pp{start}-{end}{pipeline_input_path.suffix}"
        with dest.open("wb") as f:
            writer.write(f)
        logger.info(
            "Stage %d: Extracted pages %d-%d from %s into the .s2l bundle (%s)",
            stage_idx, start, end, pipeline_input_path, relative(dest, stage_output_dir.parent),
        )
    else:
        dest = stage_output_dir / f"original{pipeline_input_path.suffix}"
        shutil.copy2(pipeline_input_path, dest)
        logger.info(
            "Stage %d: Copied the original score %s into the .s2l bundle (%s)",
            stage_idx, pipeline_input_path, relative(dest, stage_output_dir.parent),
        )

    yield dest


def _collect_score_info(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    logger.info("Stage %d: Collecting score information...", stage_idx)
    pipeline_output_dir = stage_output_dir.parent
    first_xml = pipeline_output_dir / min(dependencies_to_outputs[Stage.MUSICXML])
    extracted = score_info.extract_from_xml(first_xml)
    cli = score_info.ScoreInfo(
        title=score_info.ScoreField(text=settings.title),
        subtitle=score_info.ScoreField(text=settings.subtitle),
        composer=score_info.ScoreField(text=settings.composer),
        work_number=score_info.ScoreField(text=settings.work_number),
        copyright=score_info.ScoreField(text=settings.copyright),
        tagline=score_info.ScoreField(text=settings.tagline),
    )
    if settings.no_prompt:
        info = score_info.combine_non_interactive(cli, extracted)
    else:
        info = score_info.collect(cli, extracted)
    dest = stage_output_dir / "score_info.json"
    score_info.save(dest, info)
    yield dest


def _preprocess(
    stage_output_dir: Path,
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
                background_normalize=settings.background_normalize,
                background_normalize_kernel=settings.background_normalize_kernel,
                trunc_threshold=settings.trunc_threshold,
                trunc_threshold_value=settings.trunc_threshold_value,
                gamma_correction=settings.gamma_correction,
                gamma=settings.gamma,
                deskew=settings.deskew,
                tight_crop=settings.tight_crop,
                clahe=settings.clahe,
                projection_k=settings.projection_k,
                projection_denoise=settings.projection_denoise,
                debug_dir=debug_dir_i,
                bundle_root=pipeline_output_dir,
            )

        page_path = stage_output_dir / f"page_{i + 1:04d}.png"
        cv2.imwrite(str(page_path), gray)
        yield page_path


def _should_run_heavy_preprocessing(source: Path, settings: ConvertSettings, stage_idx: int) -> bool:
    if settings.preprocessing_is_noop():
        logger.info("Stage %d: No preprocessing operations enabled, skipping.", stage_idx)
        return False
    if settings.pdf_kind is PdfKind.VECTOR:
        logger.info("Stage %d: Vector PDF, skipping heavy preprocessing.", stage_idx)
        return False
    if settings.pdf_kind is PdfKind.SCAN:
        logger.info("Stage %d: Scan PDF, running heavy preprocessing.", stage_idx)
        return True
    if pdf.is_vector(source):
        logger.info("Stage %d: Vector PDF detected, skipping heavy preprocessing.", stage_idx)
        return False
    logger.info("Stage %d: Scan detected, running heavy preprocessing.", stage_idx)
    return True


def _omr(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    page_paths = sorted(
        pipeline_output_dir / p for p in dependencies_to_outputs[Stage.PREPROCESS]
    )

    # Build the combined PDF first so the book OMR can start immediately.
    logger.info("Stage %d: Building combined PDF for full-score OMR...", stage_idx)
    score_pdf = stage_output_dir / "book.pdf"
    pdf.build_omr_pdf(page_paths, score_pdf)

    pages_dir = stage_output_dir / "pages"
    pages_dir.mkdir()

    # Run book OMR and all per-page OMRs concurrently.
    logger.info("Stage %d: Running OMR on %d page(s) + full score in parallel...", stage_idx, len(page_paths))
    with ThreadPoolExecutor() as executor:
        book_future: Future[Path] = executor.submit(audiveris.run_omr, score_pdf, stage_output_dir, stage_idx, pipeline_output_dir)
        page_futures: dict[Future[Path], Path] = {
            executor.submit(audiveris.run_omr, page_path, pages_dir, stage_idx, pipeline_output_dir): page_path
            for page_path in page_paths
        }

    for future, page_path in page_futures.items():
        page_num = int(page_path.stem.split("_")[-1])
        try:
            yield future.result()
        except RuntimeError as e:
            logger.warning(
                "Stage %d: OMR failed for page %d — no layout data for this page "
                "(hopefully a non-musical page such as a cover). PNG: %s. Error: %s",
                stage_idx, page_num, relative(page_path, pipeline_output_dir), e,
            )

    yield book_future.result()


def _export_musicxml(
    input_xml_path: Path | None,
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent

    if input_xml_path is not None:
        dest = stage_output_dir / input_xml_path.name
        shutil.copy2(input_xml_path, dest)
        logger.info(
            "Stage %d: Copied user-provided MusicXML %s into the .s2l bundle (%s)",
            stage_idx, input_xml_path, relative(dest, pipeline_output_dir),
        )
        yield dest
    else:
        book_omr = next(
            pipeline_output_dir / p
            for p in dependencies_to_outputs[Stage.OMR]
            if Path(p).name == "book.omr"
        )
        yield audiveris.export_xml(book_omr, stage_output_dir, stage_idx, pipeline_output_dir)


def _clean_musicxml(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    xml_path = pipeline_output_dir / dependencies_to_outputs[Stage.MUSICXML][0]
    dest = stage_output_dir / xml_path.with_suffix(".clean" + xml_path.suffix).name
    musicxml_cleanup.clean(xml_path, dest)
    yield dest


def _extract_layout(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent

    page_omr_by_num = {
        int(Path(p).stem.split("_")[-1]): pipeline_output_dir / p
        for p in dependencies_to_outputs[Stage.OMR]
        if Path(p).parent.name == "pages"
    }
    book_omr = next(
        pipeline_output_dir / p
        for p in dependencies_to_outputs[Stage.OMR]
        if Path(p).name == "book.omr"
    )

    combined_sheets = []
    measure_offset = 0
    global_system_id = 0
    for page_num, omr_path in sorted(page_omr_by_num.items()):
        result, measure_offset = omr_layout.extract(omr_path, stage_idx, initial_measure_offset=measure_offset)
        for sheet in result["sheets"]:
            sheet["sheet"] = page_num
            for system in sheet["systems"]:
                global_system_id += 1
                system["local_id"] = system.pop("id")
                system["global_id"] = global_system_id
            combined_sheets.append(sheet)

    _validate_layout_against_book(combined_sheets, book_omr, stage_output_dir, stage_idx)

    dest = stage_output_dir / "layout.json"
    dest.write_text(json.dumps({"sheets": combined_sheets}, indent=2))
    yield dest


def _validate_layout_against_book(
    page_sheets: list[dict],
    book_omr_path: Path,
    stage_output_dir: Path,
    stage_idx: int,
) -> None:
    book_result, _ = omr_layout.extract(book_omr_path, stage_idx)

    debug_path = stage_output_dir / "book_layout_debug.json"
    debug_path.write_text(json.dumps(book_result, indent=2))

    book_by_page = {sheet["sheet"]: sheet for sheet in book_result["sheets"]}

    for page_sheet in page_sheets:
        page_num = page_sheet["sheet"]
        book_sheet = book_by_page.get(page_num)
        if book_sheet is None:
            raise PipelineError(
                f"Stage {stage_idx}: Page {page_num} present in per-page layout but missing from book OMR."
            )

        page_systems = page_sheet["systems"]
        book_systems = book_sheet["systems"]

        if len(page_systems) != len(book_systems):
            raise PipelineError(
                f"Stage {stage_idx}: Layout mismatch on page {page_num}: "
                f"per-page OMR has {len(page_systems)} system(s), book OMR has {len(book_systems)}."
            )

        for sys_i, (page_sys, book_sys) in enumerate(zip(page_systems, book_systems)):
            if page_sys["measure_range"] != book_sys["measure_range"]:
                raise PipelineError(
                    f"Stage {stage_idx}: Layout mismatch on page {page_num}, "
                    f"system {sys_i + 1} (in-page index): "
                    f"per-page measure range {page_sys['measure_range']} vs book OMR {book_sys['measure_range']}."
                )

    per_page_nums = {sheet["sheet"] for sheet in page_sheets}
    for page_num, book_sheet in book_by_page.items():
        if page_num not in per_page_nums and book_sheet["systems"]:
            raise PipelineError(
                f"Stage {stage_idx}: Page {page_num} is absent from per-page OMR but has "
                f"{len(book_sheet['systems'])} system(s) in book OMR — expected no musical content."
            )


def _crop_images(
    stage_output_dir: Path,
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


def _extract_xml_snippets(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent

    layout_path = pipeline_output_dir / dependencies_to_outputs[Stage.LAYOUT][0]
    layout = json.loads(layout_path.read_text())

    clean_xml_path = pipeline_output_dir / dependencies_to_outputs[Stage.CLEAN_XML][0]

    systems_dir = stage_output_dir / "systems"
    measures_dir = stage_output_dir / "measures"
    systems_dir.mkdir()
    measures_dir.mkdir()

    all_systems = [system for sheet in layout["sheets"] for system in sheet["systems"]]
    yield from musicxml_snippets.extract_snippets(clean_xml_path, all_systems, systems_dir, measures_dir)


def _merge_ly(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    clean_xml_path = pipeline_output_dir / dependencies_to_outputs[Stage.CLEAN_XML][0]

    info = score_info.load(pipeline_output_dir / dependencies_to_outputs[Stage.SCORE_INFO][0])
    ly_header = score_info.build_ly_header(info)

    dest = stage_output_dir / "score.ly"
    ly_merge.merge_ly(clean_xml_path, dest, stage_idx, ly_header)

    link = pipeline_output_dir / "transcription.ly"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(dest.relative_to(pipeline_output_dir, walk_up=True))

    yield dest


def _render_ly(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    score_ly_rel = dependencies_to_outputs[Stage.LILYPOND][0]
    score_ly = pipeline_output_dir / score_ly_rel
    dest = stage_output_dir / "score.pdf"
    lilypond.render(score_ly, dest, stage_idx)

    link = pipeline_output_dir / "transcription.pdf"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(dest.relative_to(pipeline_output_dir, walk_up=True))

    yield dest


def _convert_ly_snippets(
    stage_output_dir: Path,
    settings: ConvertSettings,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    stage_idx: int,
) -> Iterable[Path]:
    pipeline_output_dir = stage_output_dir.parent
    xml_paths = sorted(
        pipeline_output_dir / p
        for p in dependencies_to_outputs[Stage.XML_SNIPPETS]
        if Path(p).parent.name == "systems"
    )

    systems_dir = stage_output_dir / "systems"
    systems_dir.mkdir()

    for i, xml_path in enumerate(xml_paths):
        logger.info("Stage %d: Converting system %d/%d...", stage_idx, i + 1, len(xml_paths))
        dest = systems_dir / xml_path.with_suffix(".ly").name
        musicxml2ly.run(xml_path, dest, stage_idx)
        yield dest
