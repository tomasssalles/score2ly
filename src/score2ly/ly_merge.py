import logging
import re
import tempfile
from pathlib import Path

from score2ly import musicxml2ly

logger = logging.getLogger(__name__)

_TESTED_MUSICXML2LY_MAJOR_VERSION = 2
_MUSICXML2LY_VERSION = re.compile(r'^\\version\s+"([^"]+)"')
_VAR_DEF = re.compile(r"^\w+ =")
_MUSICXML2LY_AUTO_COMMENT = re.compile(r"^% automatically converted by musicxml2ly .+")
_HEADER_BLOCK_START = re.compile(r"\\header\b")
_INSTRUMENT_NAME_LINE = re.compile(r"^[ \t]*\\set\s+\w+\.instrumentName\s*=.*(?:\n|$)", re.MULTILINE)
_SHORT_INSTRUMENT_NAME_LINE = re.compile(r"^[ \t]*\\set\s+\w+\.shortInstrumentName\s*=.*(?:\n|$)", re.MULTILINE)


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


def merge_ly(clean_xml_path: Path, output_ly: Path, stage: int, ly_header: str) -> None:
    """Convert the clean MusicXML into a single LilyPond score via musicxml2ly."""
    tmp_ly = Path(tempfile.gettempdir()) / f"score2ly_{output_ly.parent.parent.name}.ly"
    musicxml2ly.run(clean_xml_path, tmp_ly, stage)
    _check_musicxml2ly_version(tmp_ly, stage)

    preamble, rest = _split_preamble(tmp_ly)
    if len(_INSTRUMENT_NAME_LINE.findall(rest)) <= 1 and len(_SHORT_INSTRUMENT_NAME_LINE.findall(rest)) <= 1:
        rest = _INSTRUMENT_NAME_LINE.sub("", rest)
        rest = _SHORT_INSTRUMENT_NAME_LINE.sub("", rest)
    output_ly.write_text(f"{preamble}\n\n{ly_header}\n\n{rest}")
