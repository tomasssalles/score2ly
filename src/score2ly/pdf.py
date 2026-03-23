import logging
import math
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

_DESIRED_DPI = 300
_AUDIVERIS_PIXEL_LIMIT = 20_000_000
_AUDIVERIS_MIN_SUGGESTED_DPI = 200
_PIXEL_TARGET_FACTOR = 0.85  # stay at 85% of the hard limit


def page_rasterization_dpi(width_pts: float, height_pts: float) -> int:
    """Return the DPI to rasterize a page at, capped to keep it under the Audiveris pixel limit."""
    width_in = width_pts / 72
    height_in = height_pts / 72
    limit_dpi = math.floor(math.sqrt(_AUDIVERIS_PIXEL_LIMIT * _PIXEL_TARGET_FACTOR / (width_in * height_in)))
    dpi = min(_DESIRED_DPI, limit_dpi)
    if dpi < _AUDIVERIS_MIN_SUGGESTED_DPI:
        logger.warning(
            "Rasterization DPI (%d) is below Audiveris's recommended minimum of %d."
            " OMR quality may be reduced.",
            dpi, _AUDIVERIS_MIN_SUGGESTED_DPI,
        )
    return dpi


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