import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_TESTED_MUSICXML2LY_MAJOR_VERSION = 2
_MUSICXML2LY_VERSION = re.compile(r'^\\version\s+"([^"]+)"')
_VAR_DEF = re.compile(r"^\w+ =")
_VAR_DEF_NAME = re.compile(r"^(\w+)(\s*=)")
_MUSICXML2LY_AUTO_COMMENT = re.compile(r"^% automatically converted by musicxml2ly .+")
_HEADER_BLOCK_START = re.compile(r"\\header\b")
_MUSICXML2LY_SCORE_DEF_COMMENT = re.compile(r"^% The score\b.*")
_SCORE_START = re.compile(r"^\\score\b")
_GROUP_TYPE = re.compile(r"\\new\s+(\w+)")
_INSTRUMENT_NAME = re.compile(r"\\set\s+\w+\.instrumentName\s*=\s*\"([^\"]+)\"")
_STAFF_CONTEXT = re.compile(r"\\context\s+Staff\s*=\s*\"([^\"]+)\"")
_VOICE_CONTEXT = re.compile(r"\\context\s+Voice\s*=\s*\"(\w+)\"")
_VOICE_ROLE = re.compile(r"\\(voice\w+)")


@dataclass
class VoiceEntry:
    name: str
    role: str  # e.g. "voiceOne", "voiceTwo", ...; defaults to "voiceOne" when unspecified in the source


@dataclass
class StaffEntry:
    id: str
    directives: list[str] = field(default_factory=list)  # lines between staff opening and first voice
    voices: list[VoiceEntry] = field(default_factory=list)


@dataclass
class ScoreStructure:
    group_type: str
    instrument_name: str
    staves: list[StaffEntry]


# Maps staff_id -> voice_role -> list of variable names across systems (None if absent in that system).
VoiceMap = dict[str, dict[str, list[str | None]]]


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


def extract_preamble(ly_file: Path) -> str:
    """Return the preamble of a musicxml2ly-generated .ly file, stripped of \\header blocks."""
    lines = ly_file.read_text().splitlines(keepends=True)
    preamble_lines = []
    brace_depth = 0
    in_header_block = False

    for line in lines:
        if _VAR_DEF.match(line):
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

    return "".join(preamble_lines).rstrip("\n")


def parse_score_block(ly_file: Path) -> ScoreStructure:
    """Parse the \\score block of a musicxml2ly-generated .ly file into a ScoreStructure."""
    lines = ly_file.read_text().splitlines()

    in_score = False
    group_type = ""
    instrument_name = ""
    staves: list[StaffEntry] = []
    current_staff: StaffEntry | None = None
    in_staff_preamble = False

    for line in lines:
        if not in_score:
            if _SCORE_START.match(line.strip()):
                in_score = True
            continue

        if not group_type and (m := _GROUP_TYPE.search(line)):
            # noinspection PyUnresolvedReferences
            group_type = m.group(1)

        if not instrument_name and (m := _INSTRUMENT_NAME.search(line)):
            # noinspection PyUnresolvedReferences
            instrument_name = m.group(1)

        if m := _STAFF_CONTEXT.search(line):
            current_staff = StaffEntry(id=m.group(1))
            staves.append(current_staff)
            in_staff_preamble = True
            continue

        if current_staff and (m := _VOICE_CONTEXT.search(line)):
            in_staff_preamble = False
            role_match = _VOICE_ROLE.search(line)
            current_staff.voices.append(VoiceEntry(
                name=m.group(1),
                role=role_match.group(1) if role_match else "voiceOne",
            ))
        elif in_staff_preamble and (stripped := line.strip()):
            current_staff.directives.append(stripped)

    return ScoreStructure(group_type=group_type, instrument_name=instrument_name, staves=staves)


def _build_voice_map(structures: Sequence[ScoreStructure]) -> VoiceMap:
    n = len(structures)

    # Collect staff_id -> role slots in order of first appearance.
    slots: dict[str, dict[str, None]] = {}
    for structure in structures:
        for staff in structure.staves:
            if staff.id not in slots:
                slots[staff.id] = {}
            for voice in staff.voices:
                slots[staff.id][voice.role] = None

    # Fill the map: for each system, record which variable name fills each slot.
    voice_map: VoiceMap = {
        staff_id: {role: [None] * n for role in roles}
        for staff_id, roles in slots.items()
    }
    for i, structure in enumerate(structures):
        for staff in structure.staves:
            for voice in staff.voices:
                voice_map[staff.id][voice.role][i] = voice.name

    return voice_map


_DIGIT_NAMES = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")


def _get_system_suffix(system_idx: int) -> str:
    digits = "".join(_DIGIT_NAMES[int(d)] for d in str(system_idx))
    return f"_s{digits}"


def extract_renamed_variables(ly_file: Path, system_idx: int) -> str:
    """Extract variable definitions from a musicxml2ly .ly file, renaming each with a per-system suffix."""
    suffix = _get_system_suffix(system_idx)
    lines = ly_file.read_text().splitlines(keepends=True)

    result = []
    in_vars = False

    for line in lines:
        if not in_vars:
            if _VAR_DEF.match(line):
                in_vars = True
            else:
                continue

        if _MUSICXML2LY_SCORE_DEF_COMMENT.match(line):
            continue

        if _SCORE_START.match(line.strip()):
            break

        result.append(_VAR_DEF_NAME.sub(rf"\1{suffix}\2", line))

    return "".join(result).rstrip("\n")


def compute_system_spacer(xml_file: Path) -> str:
    """Return a LilyPond spacer rest string covering the full duration of a system.

    Emits one s1*beats/beat-type token per measure, handling mid-system time signature changes.
    """
    part = ElementTree.parse(xml_file).getroot().find(".//part")
    if part is None:
        raise ValueError(f"No <part> element found in {xml_file}")

    beats, beat_type = 4, 4  # fallback default; should always be overridden by the first measure
    spacers = []

    for measure in part.findall("measure"):
        time_el = measure.find("attributes/time")
        if time_el is not None:
            beats = int(time_el.findtext("beats"))
            beat_type = int(time_el.findtext("beat-type"))
        spacers.append(f"s1*{beats}/{beat_type}")

    return " | ".join(spacers)


def _merged_var_name(staff_idx: int, voice_idx: int) -> str:
    staff = "".join(_DIGIT_NAMES[int(d)] for d in str(staff_idx))
    voice = "".join(_DIGIT_NAMES[int(d)] for d in str(voice_idx))
    return f"Staff{staff}Voice{voice}"


def _canonical_staff_directives(structures: Sequence[ScoreStructure]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for structure in structures:
        for staff in structure.staves:
            if staff.id not in result or (not result[staff.id] and staff.directives):
                result[staff.id] = staff.directives
    return result


def build_score_block(structures: Sequence[ScoreStructure], voice_map: VoiceMap) -> str:
    first = structures[0]
    group_type = first.group_type
    staff_directives = _canonical_staff_directives(structures)

    lines = ["\\score {", "    <<", f"        \\new {group_type}", "        <<"]

    for staff_idx, (staff_id, roles) in enumerate(voice_map.items(), start=1):
        lines.append(f"            \\context Staff = \"{staff_id}\" <<")
        for directive in staff_directives.get(staff_id, []):
            lines.append(f"                {directive}")
        for voice_idx, role in enumerate(roles.keys(), start=1):
            merged_name = _merged_var_name(staff_idx, voice_idx)
            lines.append(f"                \\context Voice = \"{merged_name}\" {{ \\{role} \\{merged_name} }}")
        lines.append("            >>")

    lines += ["        >>", "    >>", "    \\layout {}", "}"]
    return "\n".join(lines)


def build_merged_variables(voice_map: VoiceMap, system_spacers: list[str]) -> str:
    """Build merged variable definitions, one per (staff, voice) slot."""
    blocks = []
    for staff_idx, (staff_id, roles) in enumerate(voice_map.items(), start=1):
        for voice_idx, (role, var_names) in enumerate(roles.items(), start=1):
            merged_name = _merged_var_name(staff_idx, voice_idx)
            lines = [f"{merged_name} = {{"]
            for i, var_name in enumerate(var_names):
                if var_name is not None:
                    lines.append(f"  \\{var_name}{_get_system_suffix(i + 1)}")
                else:
                    lines.append(f"  {system_spacers[i]}")
            lines.append("}")
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def merge_musicxml2ly(ly_xml_pairs: Sequence[tuple[Path, Path]], output_ly: Path, stage: int, ly_header: str) -> None:
    logger.info("Stage %d: Merging %d LilyPond snippet(s)...", stage, len(ly_xml_pairs))
    ly_paths = [ly for ly, _ in ly_xml_pairs]
    xml_paths = [xml for _, xml in ly_xml_pairs]
    _check_musicxml2ly_version(ly_paths[0], stage)
    preamble = extract_preamble(ly_paths[0])
    structures = [parse_score_block(p) for p in ly_paths]
    voice_map = _build_voice_map(structures)
    logger.debug("Stage %d: Voice map: %s", stage, voice_map)
    renamed_vars = [extract_renamed_variables(ly, i + 1) for i, ly in enumerate(ly_paths)]
    logger.debug("Stage %d: Renamed variables collected for %d systems.", stage, len(renamed_vars))
    logger.debug("Stage %d: Renamed variables for system 1:\n%s", stage, renamed_vars[0])
    system_spacers = [compute_system_spacer(xml) for xml in xml_paths]
    logger.debug("Stage %d: System spacers: %s", stage, system_spacers)
    merged_vars = build_merged_variables(voice_map, system_spacers)
    logger.debug("Stage %d: Merged variables:\n%s", stage, merged_vars)

    score_block = build_score_block(structures, voice_map)
    all_renamed = "\n\n".join(renamed_vars)
    output_ly.write_text(f"{preamble}\n\n{ly_header}\n\n{all_renamed}\n\n{merged_vars}\n\n{score_block}\n")
