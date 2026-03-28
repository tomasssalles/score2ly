import copy
import re
from collections.abc import Collection
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

# Attributes stripped from every element
_COORD_ATTRS = frozenset({"default-x", "default-y", "relative-x", "relative-y"})
_STYLE_ATTRS = frozenset({"font-family", "font-size", "font-weight", "font-style",
                           "color", "halign", "valign"})
_GLOBAL_ATTRS_TO_STRIP = _COORD_ATTRS | _STYLE_ATTRS

# Element-specific attribute stripping
_ACCIDENTAL_ATTRS_TO_STRIP = frozenset({"bracket", "size", "cautionary"})
_SLUR_ATTRS_TO_STRIP = frozenset({"bezier-x", "bezier-y", "bezier-x2", "bezier-y2", "placement"})
_PLACEMENT_ELEMENTS = frozenset({"direction", "staccato", "strong-accent", "accent", "tenuto",
                                  "detached-legato", "stressed", "unstressed", "tuplet"})
_STAFF_DETAILS_ATTRS_TO_STRIP = frozenset({"print-object"})

# Top-level elements to remove entirely
_TOPLEVEL_REMOVE = frozenset({"work", "identification", "defaults", "credit",
                               "movement-number", "movement-title"})

# Children of <score-part> to remove
_SCORE_PART_REMOVE = frozenset({"score-instrument", "midi-instrument", "midi-device"})

# Attributes carried forward from page to page when not reprinted
_PAGE_CARRY_FORWARD_TAGS = frozenset({"time", "key"})


def clean(
    input_path: Path,
    output_path: Path,
    first_measure: int = 1,
    carried_attrs: dict | None = None,
) -> tuple[int, dict]:
    """Clean the MusicXML file and renumber measures starting from first_measure.

    Returns (first_measure_for_next_page, carried_attrs_for_next_page).
    """
    carried_attrs = carried_attrs or {}

    raw = input_path.read_text(encoding="utf-8")
    doctype = _extract_doctype(raw)

    tree = ElementTree.parse(input_path)
    root = tree.getroot()

    # Remove top-level noise
    _remove_children(root, _TOPLEVEL_REMOVE)

    # Simplify part-list
    for score_part in root.findall("part-list/score-part"):
        _remove_children(score_part, _SCORE_PART_REMOVE)

    # Remove <print> blocks from every measure and apply global numbering
    measure_count = 0
    for measure in root.iter("measure"):
        measure.set("number", str(first_measure + measure_count))
        measure.attrib.pop("width", None)
        _remove_children(measure, {"print"})
        measure_count += 1

    # Strip coordinate and style attributes from all elements
    for el in root.iter():
        for attr in _GLOBAL_ATTRS_TO_STRIP:
            el.attrib.pop(attr, None)

    # Element-specific cleanup
    for accidental in root.iter("accidental"):
        for attr in _ACCIDENTAL_ATTRS_TO_STRIP:
            accidental.attrib.pop(attr, None)

    for sound in root.iter("sound"):
        sound.attrib.pop("dynamics", None)

    for slur in root.iter("slur"):
        for attr in _SLUR_ATTRS_TO_STRIP:
            slur.attrib.pop(attr, None)

    for tag in _PLACEMENT_ELEMENTS:
        for el in root.iter(tag):
            el.attrib.pop("placement", None)

    for staff_details in root.iter("staff-details"):
        for attr in _STAFF_DETAILS_ATTRS_TO_STRIP:
            staff_details.attrib.pop(attr, None)

    # Inject carried attributes into first measure if missing
    first_measure_el = next(root.iter("measure"), None)
    if first_measure_el is not None and carried_attrs:
        inject_missing_attrs(first_measure_el, carried_attrs)

    # Normalize time signatures: recompute from note durations, replacing Audiveris's
    initial_time: tuple[int, int] | None = None
    time_el = carried_attrs.get(("time", None))
    if time_el is not None:
        xml_beats = time_el.findtext("beats")
        xml_beat_type = time_el.findtext("beat-type")
        if xml_beats and xml_beat_type:
            initial_time = (int(xml_beats), int(xml_beat_type))
    _normalize_time_signatures(root, initial_time)

    # Pad any voice that ends before the measure duration with <forward> elements
    _pad_all_voices(root)

    # Collect time/key from this page to carry forward to the next
    new_carried = dict(carried_attrs)
    for measure in root.iter("measure"):
        for attrs_el in measure.findall("attributes"):
            for child in attrs_el:
                if child.tag in _PAGE_CARRY_FORWARD_TAGS:
                    new_carried[(child.tag, child.attrib.get("number"))] = copy.deepcopy(child)

    ElementTree.indent(root, space="  ")
    xml_body = ElementTree.tostring(root, encoding="unicode", xml_declaration=False)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    if doctype:
        parts.append(doctype)
    parts.append(xml_body)
    output_path.write_text("\n".join(parts), encoding="utf-8")
    return first_measure + measure_count, new_carried


def inject_missing_attrs(measure: ElementTree.Element, carried: dict) -> None:
    attrs_el = measure.find("attributes")
    if attrs_el is None:
        attrs_el = ElementTree.Element("attributes")
        measure.insert(0, attrs_el)

    div_idx = next((i for i, c in enumerate(attrs_el) if c.tag == "divisions"), -1)
    insert_pos = div_idx + 1 if div_idx >= 0 else 0

    injected = 0
    for (tag, number), element in carried.items():
        already = any(
            c.tag == tag and c.attrib.get("number") == number
            for c in attrs_el
        )
        if not already:
            attrs_el.insert(insert_pos + injected, copy.deepcopy(element))
            injected += 1


def voice_end_positions(measure: ElementTree.Element) -> tuple[dict[str, int], dict[str, str]]:
    """Return (voice_end, voice_staff) for all voices with content in the measure.

    voice_end maps voice_id -> cursor position after the voice's last note/forward.
    voice_staff maps voice_id -> staff number (from the most recently seen note/forward).
    """
    cursor = 0
    voice_end: dict[str, int] = {}
    voice_staff: dict[str, str] = {}

    for child in measure:
        if child.tag == "note":
            voice_id = child.findtext("voice")
            staff_id = child.findtext("staff")
            if voice_id and staff_id:
                voice_staff[voice_id] = staff_id
            if child.find("chord") is None:
                dur = int(child.findtext("duration") or "0")
                cursor += dur
                if voice_id:
                    voice_end[voice_id] = cursor
        elif child.tag == "backup":
            dur = int(child.findtext("duration") or "0")
            cursor = max(0, cursor - dur)
        elif child.tag == "forward":
            dur = int(child.findtext("duration") or "0")
            cursor += dur
            voice_id = child.findtext("voice")
            staff_id = child.findtext("staff")
            if voice_id:
                if staff_id:
                    voice_staff[voice_id] = staff_id
                voice_end[voice_id] = cursor

    return voice_end, voice_staff


def _pad_voices_in_measure(measure: ElementTree.Element, measure_duration: int) -> None:
    """Append <forward> elements for any voice that ends before measure_duration."""
    voice_end, voice_staff = voice_end_positions(measure)
    for voice_id, end_pos in voice_end.items():
        gap = measure_duration - end_pos
        if gap > 0:
            fwd = ElementTree.SubElement(measure, "forward")
            ElementTree.SubElement(fwd, "duration").text = str(gap)
            ElementTree.SubElement(fwd, "voice").text = voice_id
            if staff_id := voice_staff.get(voice_id):
                ElementTree.SubElement(fwd, "staff").text = staff_id


def _pad_all_voices(root: ElementTree.Element) -> None:
    """For each measure in each part, pad short voices to their full measure duration."""
    for part in root.findall("part"):
        divisions = 1
        beats, beat_type = 4, 4
        for measure in part.findall("measure"):
            div_text = measure.findtext("attributes/divisions")
            if div_text:
                divisions = int(div_text)
            xml_beats = measure.findtext("attributes/time/beats")
            xml_beat_type = measure.findtext("attributes/time/beat-type")
            if xml_beats and xml_beat_type:
                beats, beat_type = int(xml_beats), int(xml_beat_type)
            measure_duration = beats * 4 * divisions // beat_type
            _pad_voices_in_measure(measure, measure_duration)


def _measure_max_duration(measure: ElementTree.Element) -> int:
    """Return the maximum forward position reached in a measure (in divisions)."""
    position = 0
    max_pos = 0
    for child in measure:
        if child.tag == "note" and child.find("chord") is None:
            dur = int(child.findtext("duration") or "0")
            position += dur
            if position > max_pos:
                max_pos = position
        elif child.tag == "backup":
            dur = int(child.findtext("duration") or "0")
            position = max(0, position - dur)
        elif child.tag == "forward":
            dur = int(child.findtext("duration") or "0")
            position += dur
            if position > max_pos:
                max_pos = position
    return max_pos


def _duration_to_time_sig(duration: int, divisions: int) -> tuple[int, int]:
    """Convert a duration in divisions to (beats, beat_type) via the simplest fraction."""
    frac = Fraction(duration, divisions)  # in quarter notes
    return frac.numerator, 4 * frac.denominator


def _normalize_time_signatures(
    root: ElementTree.Element,
    initial_time: tuple[int, int] | None,
) -> None:
    """Recompute time signatures from note durations and replace the XML's entries.

    Uses the first part's measure durations as ground truth.  Audiveris's time
    signature hints guide the tracked signature; the computed duration overrides
    when it disagrees.  Time elements are stripped from all parts and reinserted
    only at the first measure and wherever the signature changes.
    """
    parts = root.findall("part")
    if not parts:
        return

    # --- Phase 1: determine effective time sig for each measure (first part only) ---
    divisions = 1
    current_sig = initial_time
    effective_sigs: list[tuple[int, int] | None] = []

    for measure in parts[0].findall("measure"):
        div_text = measure.findtext("attributes/divisions")
        if div_text:
            divisions = int(div_text)

        # Update with Audiveris hint if present
        xml_beats = measure.findtext("attributes/time/beats")
        xml_beat_type = measure.findtext("attributes/time/beat-type")
        if xml_beats and xml_beat_type:
            current_sig = (int(xml_beats), int(xml_beat_type))

        # Compute actual duration; override tracked sig if the duration is incompatible
        dur = _measure_max_duration(measure)
        if dur > 0:
            actual = Fraction(dur, divisions)  # in quarter notes
            if current_sig is None:
                current_sig = _duration_to_time_sig(dur, divisions)
            else:
                sig_duration = Fraction(current_sig[0] * 4, current_sig[1])
                if actual != sig_duration:
                    current_sig = _duration_to_time_sig(dur, divisions)

        effective_sigs.append(current_sig)

    # --- Phase 2: strip all <time> elements and reinsert at changes ---
    for part in parts:
        last_inserted = initial_time
        for idx, measure in enumerate(part.findall("measure")):
            for attrs_el in measure.findall("attributes"):
                for time_el in list(attrs_el.findall("time")):
                    attrs_el.remove(time_el)

            sig = effective_sigs[idx] if idx < len(effective_sigs) else current_sig
            if sig is None or sig == last_inserted:
                continue

            attrs_el = measure.find("attributes")
            if attrs_el is None:
                attrs_el = ElementTree.Element("attributes")
                measure.insert(0, attrs_el)

            time_el = ElementTree.Element("time")
            ElementTree.SubElement(time_el, "beats").text = str(sig[0])
            ElementTree.SubElement(time_el, "beat-type").text = str(sig[1])
            div_idx = next((j for j, c in enumerate(attrs_el) if c.tag == "divisions"), -1)
            attrs_el.insert(div_idx + 1, time_el)
            last_inserted = sig


def _remove_children(parent: ElementTree.Element, tags: Collection[str]) -> None:
    for child in list(parent):
        if child.tag in tags:
            parent.remove(child)


def _extract_doctype(raw: str) -> str | None:
    m = re.search(r"<!DOCTYPE[^>]+>", raw)
    return m.group(0) if m else None
