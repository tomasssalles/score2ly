import json
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

_FIELDS = [
    ("title",       "Title"),
    ("composer",    "Composer"),
    ("work_number", "Work number (e.g. Op. 45, BWV 772, K. 331)"),
    ("copyright",   "Copyright / license"),
    ("comment",     "Comment (tagline)"),
]


@dataclass
class ScoreInfo:
    title: str = ""
    composer: str = ""
    work_number: str = ""
    copyright: str = ""
    comment: str = ""


def load(path: Path) -> ScoreInfo:
    data = json.loads(path.read_text())
    return ScoreInfo(**data)


def save(path: Path, info: ScoreInfo) -> None:
    path.write_text(json.dumps({
        "title": info.title,
        "composer": info.composer,
        "work_number": info.work_number,
        "copyright": info.copyright,
        "comment": info.comment,
    }, indent=2))


def collect(overrides: ScoreInfo) -> ScoreInfo:
    """Prompt the user for each field, using overrides as defaults."""
    print("\nEnter score information (press Enter to keep the value in brackets, or leave empty):")
    result = {}
    for key, label in _FIELDS:
        current = getattr(overrides, key)
        prompt = f"  {label}"
        if current:
            prompt += f" [{current}]"
        prompt += ": "
        value = input(prompt).strip()
        result[key] = value if value else current
    return ScoreInfo(**result)


def inject_into_xml(xml_path: Path, info: ScoreInfo) -> None:
    """Inject score info into the top-level elements of a clean MusicXML file."""
    raw = xml_path.read_text(encoding="utf-8")
    doctype_match = re.search(r"<!DOCTYPE[^>]+>", raw)
    doctype = doctype_match.group(0) if doctype_match else None

    tree = ET.parse(xml_path)
    root = tree.getroot()

    insert_idx = 0

    if info.work_number:
        work = ET.Element("work")
        ET.SubElement(work, "work-number").text = info.work_number
        root.insert(insert_idx, work)
        insert_idx += 1

    if info.title:
        mt = ET.Element("movement-title")
        mt.text = info.title
        root.insert(insert_idx, mt)
        insert_idx += 1

    identification = ET.Element("identification")
    has_identification = False
    if info.composer:
        creator = ET.SubElement(identification, "creator", attrib={"type": "composer"})
        creator.text = info.composer
        has_identification = True
    if info.copyright:
        ET.SubElement(identification, "rights").text = info.copyright
        has_identification = True
    if info.comment:
        misc = ET.SubElement(identification, "miscellaneous")
        ET.SubElement(misc, "miscellaneous-field", attrib={"name": "tagline"}).text = info.comment
        has_identification = True
    if has_identification:
        root.insert(insert_idx, identification)

    ET.indent(root, space="  ")
    xml_body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    if doctype:
        parts.append(doctype)
    parts.append(xml_body)
    xml_path.write_text("\n".join(parts), encoding="utf-8")