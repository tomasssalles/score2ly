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


def extract_from_xml(xml_path: Path) -> ScoreInfo:
    """Extract score info from a raw MusicXML file (e.g. Audiveris output)."""
    root = ET.parse(xml_path).getroot()
    title = (root.findtext("movement-title") or "").strip()
    work_number = (root.findtext("work/work-number") or "").strip()
    composer = ""
    for creator in root.findall("identification/creator"):
        if creator.get("type") == "composer":
            composer = (creator.text or "").strip()
            break
    copyright = (root.findtext("identification/rights") or "").strip()
    return ScoreInfo(title=title, composer=composer, work_number=work_number, copyright=copyright)


def collect(cli: ScoreInfo, extracted: ScoreInfo) -> ScoreInfo:
    """Prompt for fields not supplied via CLI, using OMR-extracted values as defaults."""
    result = {}
    queries = []
    for key, label in _FIELDS:
        cli_value = getattr(cli, key)
        if cli_value:
            result[key] = cli_value
        else:
            queries.append((key, label, getattr(extracted, key)))

    if queries:
        print("\nEnter score information (press Enter to keep the value in brackets, '-' to clear):")
        for key, label, default in queries:
            prompt = f"  {label} [{default or '<empty>'}]: "
            value = input(prompt).strip()
            result[key] = "" if value == "-" else (value or default)

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