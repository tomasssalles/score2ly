import logging
import zipfile
from pathlib import Path
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_TESTED_AUDIVERIS_MAJOR_VERSION = 5
_INTERLINE_PADDING_FACTOR = 4.5


def extract(omr_path: Path, stage: int, initial_measure_offset: int = 0) -> tuple[dict, int]:
    with zipfile.ZipFile(omr_path) as z:
        book = ElementTree.fromstring(z.read("book.xml"))
        _check_audiveris_version(book, stage)

        sheets_out = []
        global_measure_offset = initial_measure_offset

        for sheet_el in book.findall("sheet"):
            sheet_num = int(sheet_el.attrib["number"])

            page_el = sheet_el.find("page")
            delta = int(page_el.attrib.get("delta-measure-id", 0)) if page_el is not None else 0

            sheet_xml = ElementTree.fromstring(z.read(f"sheet#{sheet_num}/sheet#{sheet_num}.xml"))

            picture = sheet_xml.find("picture")
            page_width = int(picture.attrib["width"])
            page_height = int(picture.attrib["height"])

            interline = _parse_interline(sheet_xml, stage)
            padding = round(interline * _INTERLINE_PADDING_FACTOR)

            page_measure_count = 0
            systems_out = []

            for sys_el in sheet_xml.find("page").findall("system"):
                sys_id = int(sys_el.attrib["id"])
                stack_els = sys_el.findall("stack")

                part = sys_el.find("part")
                staves = part.findall("staff") if part is not None else []

                glyph_bounds = _collect_glyph_bounds(sys_el, stage)
                staff_extent = _staff_line_extent(staves)
                sys_bounds = _system_bounds(staff_extent, glyph_bounds, padding, page_height)

                stack_ids = [int(s.attrib["id"]) for s in stack_els]
                if stack_ids and stack_ids != list(range(stack_ids[0], stack_ids[0] + len(stack_ids))):
                    logger.warning(
                        "Stage %d: System %d stack IDs are not consecutive: %s — processing in document order.",
                        stage, sys_id, stack_ids,
                    )

                stack_lefts = [int(s.attrib["left"]) for s in stack_els]
                if stack_lefts != sorted(stack_lefts):
                    logger.warning(
                        "Stage %d: System %d stacks are not in left-to-right order — sorting by x-coordinate.",
                        stage, sys_id,
                    )
                    stack_els = sorted(stack_els, key=lambda s: int(s.attrib["left"]))

                measures_out = []
                for stack in stack_els:
                    page_measure_count += 1
                    local_id = int(stack.attrib["id"])
                    global_id = global_measure_offset + page_measure_count
                    stack_left = int(stack.attrib["left"])
                    stack_right = int(stack.attrib["right"])
                    meas_bounds = _measure_bounds(stack_left, stack_right, sys_bounds)
                    measures_out.append({
                        "local_id": local_id,
                        "global_id": global_id,
                        "bounds": meas_bounds,
                    })

                systems_out.append({
                    "id": sys_id,
                    "bounds": sys_bounds,
                    "measure_range": [measures_out[0]["global_id"], measures_out[-1]["global_id"]],
                    "measures": measures_out,
                })

            sheets_out.append({
                "sheet": sheet_num,
                "width": page_width,
                "height": page_height,
                "systems": systems_out,
            })

            global_measure_offset += delta

    return {"sheets": sheets_out}, global_measure_offset


def _check_audiveris_version(book: ElementTree.Element, stage: int) -> None:
    version = book.attrib.get("software-version", "")

    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        logger.warning(
            "Stage %d: This code was tested with Audiveris %d.*; Could not parse Audiveris version used here: %r. "
            "Results may be incorrect.",
            stage, _TESTED_AUDIVERIS_MAJOR_VERSION, version,
        )
        return

    if major != _TESTED_AUDIVERIS_MAJOR_VERSION:
        logger.warning(
            "Stage %d: This code was tested with Audiveris %d.*; Detected version %s. "
            "Results may be incorrect.",
            stage, _TESTED_AUDIVERIS_MAJOR_VERSION, version,
        )


def _parse_interline(sheet_xml: ElementTree.Element, stage: int) -> float:
    try:
        interline_el = sheet_xml.find("scale/interline")
        if interline_el is not None:
            return float(interline_el.attrib["main"])
    except (KeyError, ValueError):
        pass
    logger.debug("Stage %d: Could not read interline from scale; Using fallback value.", stage)
    return 20.0


def _collect_glyph_bounds(sys_el: ElementTree.Element, stage: int) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) for every symbol in the system that has a bounds element."""
    result = []
    try:
        sig = sys_el.find("sig")
        if sig is None:
            return result
        inters = sig.find("inters")
        if inters is None:
            return result
        for symbol in inters:
            b = symbol.find("bounds")
            if b is None:
                continue
            try:
                result.append((
                    int(b.attrib["x"]),
                    int(b.attrib["y"]),
                    int(b.attrib["w"]),
                    int(b.attrib["h"]),
                ))
            except (KeyError, ValueError):
                pass
    except Exception:
        logger.debug("Stage %d: Failed to collect glyph bounds; Falling back to staff-line bounds only.", stage)
    return result


def _staff_line_extent(staves: list) -> tuple[int, int, int, int]:
    """Return (x, y, right, bottom) from the outermost staff lines."""
    lefts, rights, tops, bottoms = [], [], [], []
    for staff in staves:
        lefts.append(int(staff.attrib["left"]))
        rights.append(int(staff.attrib["right"]))
        lines = staff.find("lines")
        if lines is None:
            continue
        all_lines = lines.findall("line")
        if not all_lines:
            continue
        first_pts = all_lines[0].findall("point")
        last_pts = all_lines[-1].findall("point")
        if first_pts:
            tops.append(float(first_pts[0].attrib["y"]))
        if last_pts:
            bottoms.append(float(last_pts[0].attrib["y"]))

    return (
        min(lefts) if lefts else 0,
        round(min(tops)) if tops else 0,
        max(rights) if rights else 0,
        round(max(bottoms)) if bottoms else 0,
    )


def _system_bounds(
    staff_extent: tuple[int, int, int, int],
    glyph_bounds: list[tuple[int, int, int, int]],
    padding: int,
    page_height: int,
) -> dict:
    sx, sy, sright, sbottom = staff_extent
    padded = (sx, max(0, sy - padding), sright, min(page_height - 1, sbottom + padding))

    if glyph_bounds:
        gx = min(b[0] for b in glyph_bounds)
        gy = min(b[1] for b in glyph_bounds)
        gr = max(b[0] + b[2] for b in glyph_bounds)
        gb = max(b[1] + b[3] for b in glyph_bounds)
        x = min(padded[0], gx)
        y = min(padded[1], gy)
        right = max(padded[2], gr)
        bottom = max(padded[3], gb)
    else:
        x, y, right, bottom = padded

    return {"x": x, "y": y, "width": right - x, "height": bottom - y}


def _measure_bounds(stack_left: int, stack_right: int, sys_bounds: dict) -> dict:
    return {"x": stack_left, "y": sys_bounds["y"], "width": stack_right - stack_left, "height": sys_bounds["height"]}
