import logging
import math
from collections.abc import Sequence
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

logger = logging.getLogger(__name__)

_DESIRED_DPI = 300
_AUDIVERIS_PIXEL_LIMIT = 20_000_000
_PIXEL_TARGET_FACTOR = 0.85  # stay at 85% of the hard limit


def page_rasterization_dpi(width_pts: float, height_pts: float) -> int:
    """Return the DPI to rasterize a page at, capped to keep it under the Audiveris pixel limit."""
    width_in = width_pts / 72
    height_in = height_pts / 72
    limit_dpi = math.floor(math.sqrt(_AUDIVERIS_PIXEL_LIMIT * _PIXEL_TARGET_FACTOR / (width_in * height_in)))
    if limit_dpi > _DESIRED_DPI:
        logger.warning(
            "Page dimensions are unusually small (%.2f x %.2f in)."
            " Rasterizing at %d DPI may yield too few pixels for reliable OMR.",
            width_in, height_in, _DESIRED_DPI,
        )
    return min(_DESIRED_DPI, limit_dpi)


def build_omr_pdf(png_paths: Sequence[Path], output_pdf: Path) -> None:
    """Build a single multi-page PDF from preprocessed page PNGs for Audiveris OMR.

    Pages are embedded at 300 DPI so Audiveris's rasterization produces
    pixel coordinates that match the source PNGs.
    """
    pages = [Image.open(p) for p in png_paths]
    if not pages:
        raise ValueError("No pages to build PDF from")
    pages[0].save(output_pdf, "PDF", resolution=_DESIRED_DPI, save_all=True, append_images=pages[1:])


def is_vector(pdf_path: Path) -> bool:
    """Return True if the PDF appears to be vector (not a scan).

    Heuristic: a scanned PDF consists of pages that each contain a single
    full-page raster image and little else. If every page has at least one
    embedded image and no other significant content, we treat it as a scan.
    """
    reader = PdfReader(pdf_path)
    for page in reader.pages:
        resources = page.get("/Resources")
        if not resources:
            return True
        xobjects = resources.get("/XObject")
        if not xobjects:
            return True
        has_image = any(
            xobjects[k].get("/Subtype") == "/Image"
            for k in xobjects
        )
        if not has_image:
            return True
    return False