import copy
import re
from collections.abc import Collection
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


def _remove_children(parent: ElementTree.Element, tags: Collection[str]) -> None:
    for child in list(parent):
        if child.tag in tags:
            parent.remove(child)


def _extract_doctype(raw: str) -> str | None:
    m = re.search(r"<!DOCTYPE[^>]+>", raw)
    return m.group(0) if m else None
