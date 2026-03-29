import logging
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

from score2ly import musicxml2ly

logger = logging.getLogger(__name__)

_TESTED_MUSICXML2LY_MAJOR_VERSION = 2
_MUSICXML2LY_VERSION = re.compile(r'^\\version\s+"([^"]+)"')
_VAR_DEF = re.compile(r"^\w+ =")
_MUSICXML2LY_AUTO_COMMENT = re.compile(r"^% automatically converted by musicxml2ly .+")
_HEADER_BLOCK_START = re.compile(r"\\header\b")


def _check_musicxml2ly_version(ly_file: Path, stage: int) -> None:
    m: re.Match[str] | None = None
    with open(ly_file) as fh:
        for line in fh:
            m = _MUSICXML2LY_VERSION.match(line)
            if m:
                break

    if not m:
        logger.warning(
            "Stage %d: This code was tested with musicxml2ly %d.*; Could not find musicxml2ly version used here. "
            "Results may be incorrect.",
            stage, _TESTED_MUSICXML2LY_MAJOR_VERSION,
        )
        return

    version = m.group(1)
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        logger.warning(
            "Stage %d: This code was tested with musicxml2ly %d.*; Could not parse musicxml2ly version used here: %r. "
            "Results may be incorrect.",
            stage, _TESTED_MUSICXML2LY_MAJOR_VERSION, version,
        )
        return

    if major != _TESTED_MUSICXML2LY_MAJOR_VERSION:
        logger.warning(
            "Stage %d: This code was tested with musicxml2ly %d.*; Detected version %s. "
            "Results may be incorrect.",
            stage, _TESTED_MUSICXML2LY_MAJOR_VERSION, version,
        )


def _split_preamble(ly_file: Path) -> tuple[str, str]:
    """Return the preamble of a musicxml2ly-generated .ly file, stripped of \\header blocks, plus the rest."""
    lines = ly_file.read_text().splitlines(keepends=True)
    preamble_lines = []
    rest_lines = []
    brace_depth = 0
    in_header_block = False
    lines_it = iter(lines)

    for line in lines_it:
        if _VAR_DEF.match(line):
            rest_lines = [line, *lines_it]
            break
        if _MUSICXML2LY_AUTO_COMMENT.match(line):
            continue

        if not in_header_block and _HEADER_BLOCK_START.search(line):
            in_header_block = True
            brace_depth = line.count("{") - line.count("}")
            if brace_depth <= 0:
                in_header_block = False
            continue

        if in_header_block:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                in_header_block = False
            continue

        preamble_lines.append(line)

    return "".join(preamble_lines).rstrip("\n"), "".join(rest_lines)


def concatenate_clean_xmls(clean_xml_paths: Sequence[Path], output_xml: Path, stage: int) -> None:
    """Concatenate clean per-page MusicXML files into a single MusicXML file.

    Uses the part-list from page 1 as canonical.  Measures from each part are
    concatenated across pages in order.  Warns if any page has a different number
    of parts or different part ID sequence from page 1.
    """
    roots = [ElementTree.parse(p).getroot() for p in clean_xml_paths]

    ref_part_ids = [p.attrib["id"] for p in roots[0].findall("part")]
    for i, root in enumerate(roots[1:], start=2):
        page_part_ids = [p.attrib["id"] for p in root.findall("part")]
        if len(page_part_ids) != len(ref_part_ids):
            logger.warning(
                "Stage %d: Page %d has %d part(s) but page 1 has %d — using page 1 part-list.",
                stage, i, len(page_part_ids), len(ref_part_ids),
            )
        elif page_part_ids != ref_part_ids:
            logger.warning(
                "Stage %d: Page %d part IDs %s differ from page 1 %s — mapping by index.",
                stage, i, page_part_ids, ref_part_ids,
            )

    new_root = ElementTree.Element(roots[0].tag, roots[0].attrib)
    new_root.append(roots[0].find("part-list"))

    for part_idx, part_id in enumerate(ref_part_ids):
        new_part = ElementTree.SubElement(new_root, "part", {"id": part_id})
        for root in roots:
            parts = root.findall("part")
            if part_idx < len(parts):
                for measure in parts[part_idx].findall("measure"):
                    new_part.append(measure)

    ElementTree.indent(new_root, space="  ")
    xml_body = ElementTree.tostring(new_root, encoding="unicode", xml_declaration=False)
    output_xml.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body, encoding="utf-8")


def merge_ly(clean_xml_paths: Sequence[Path], output_ly: Path, stage: int, ly_header: str) -> None:
    """Merge clean per-page MusicXMLs into a single LilyPond score via musicxml2ly."""
    tmp = Path(tempfile.gettempdir()) / f"score2ly_{output_ly.parent.parent.name}_merged.xml"
    logger.info("Stage %d: Concatenating %d clean XML(s) into %s...", stage, len(clean_xml_paths), tmp)
    concatenate_clean_xmls(clean_xml_paths, tmp, stage)

    tmp_ly = tmp.with_suffix(".ly")
    musicxml2ly.run(tmp, tmp_ly, stage)
    _check_musicxml2ly_version(tmp_ly, stage)

    preamble, rest = _split_preamble(tmp_ly)
    output_ly.write_text(f"{preamble}\n\n{ly_header}\n\n{rest}")
