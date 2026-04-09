import math
from collections.abc import Sequence
from enum import Enum
from pathlib import Path

import img2pdf
from pypdf import PdfReader


class PdfKind(str, Enum):
    AUTO = "auto"
    VECTOR = "vector"
    SCAN = "scan"

_PDF_POINTS_PER_INCH = 72  # defined by the PDF/PostScript specification
_DESIRED_DPI = 300
_AUDIVERIS_PIXEL_LIMIT = 20_000_000
_PIXEL_TARGET_FACTOR = 0.85  # stay at 85% of the hard limit


def page_rasterization_dpi(width_pts: float, height_pts: float) -> int:
    """Return the highest DPI that keeps the rasterized page within the Audiveris pixel limit."""
    width_in = width_pts / _PDF_POINTS_PER_INCH
    height_in = height_pts / _PDF_POINTS_PER_INCH
    area_sq_in = width_in * height_in
    total_pixels_limit = _AUDIVERIS_PIXEL_LIMIT * _PIXEL_TARGET_FACTOR
    pixels_per_sq_in_limit = total_pixels_limit / area_sq_in
    fractional_dpi_limit = math.sqrt(pixels_per_sq_in_limit)
    return math.floor(fractional_dpi_limit)


def build_omr_pdf(png_paths: Sequence[Path], output_pdf: Path) -> None:
    """Build a single multi-page PDF from preprocessed page PNGs for Audiveris OMR.

    Pages are embedded at 300 DPI so Audiveris's rasterization produces
    pixel coordinates that match the source PNGs.
    """
    if not png_paths:
        raise ValueError("No pages to build PDF from")
    layout = img2pdf.get_fixed_dpi_layout_fun(_DESIRED_DPI)
    output_pdf.write_bytes(img2pdf.convert([str(p) for p in png_paths], layout_fun=layout))


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