from pathlib import Path

from pypdf import PdfReader


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