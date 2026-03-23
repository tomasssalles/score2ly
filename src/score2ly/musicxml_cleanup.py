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

# Top-level elements to remove entirely
_TOPLEVEL_REMOVE = frozenset({"work", "identification", "defaults", "credit"})

# Children of <score-part> to remove
_SCORE_PART_REMOVE = frozenset({"score-instrument", "midi-instrument", "midi-device"})


def clean(input_path: Path, output_path: Path) -> None:
    raw = input_path.read_text(encoding="utf-8")
    doctype = _extract_doctype(raw)

    tree = ElementTree.parse(input_path)
    root = tree.getroot()

    # Remove top-level noise
    _remove_children(root, _TOPLEVEL_REMOVE)

    # Simplify part-list
    for score_part in root.findall("part-list/score-part"):
        _remove_children(score_part, _SCORE_PART_REMOVE)

    # Remove <print> blocks from every measure
    for measure in root.iter("measure"):
        measure.attrib.pop("width", None)
        _remove_children(measure, {"print"})

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

    ElementTree.indent(root, space="  ")
    xml_body = ElementTree.tostring(root, encoding="unicode", xml_declaration=False)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    if doctype:
        parts.append(doctype)
    parts.append(xml_body)
    output_path.write_text("\n".join(parts), encoding="utf-8")


def _remove_children(parent: ElementTree.Element, tags: Collection[str]) -> None:
    for child in list(parent):
        if child.tag in tags:
            parent.remove(child)


def _extract_doctype(raw: str) -> str | None:
    m = re.search(r"<!DOCTYPE[^>]+>", raw)
    return m.group(0) if m else None
