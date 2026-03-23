import copy
from collections.abc import Sequence, Iterable
from pathlib import Path
from xml.etree import ElementTree


def extract_page_snippets(
    clean_xml_path: Path,
    systems: Sequence[dict],
    systems_dir: Path,
    measures_dir: Path,
) -> Iterable[Path]:
    tree = ElementTree.parse(clean_xml_path)
    root = tree.getroot()
    part_list = root.find("part-list")
    parts = root.findall("part")

    for system in systems:
        measure_numbers = {m["global_id"] for m in system["measures"]}

        sys_path = systems_dir / f"system_{system['global_id']:04d}.xml"
        _write_snippet(root, part_list, parts, measure_numbers, sys_path)
        yield sys_path

        for measure in system["measures"]:
            meas_path = measures_dir / f"measure_{measure['global_id']:04d}.xml"
            _write_snippet(root, part_list, parts, {measure["global_id"]}, meas_path)
            yield meas_path


def _write_snippet(
    root: ElementTree.Element,
    part_list: ElementTree.Element,
    parts: list[ElementTree.Element],
    measure_numbers: set[int],
    output_path: Path,
) -> None:
    new_root = ElementTree.Element("score-partwise")
    if "version" in root.attrib:
        new_root.set("version", root.attrib["version"])
    new_root.append(copy.deepcopy(part_list))

    for part in parts:
        new_part = ElementTree.SubElement(new_root, "part")
        new_part.set("id", part.attrib["id"])
        for measure in part.findall("measure"):
            if int(measure.attrib["number"]) in measure_numbers:
                new_part.append(copy.deepcopy(measure))

    ElementTree.indent(new_root, space="  ")
    xml_body = ElementTree.tostring(new_root, encoding="unicode", xml_declaration=False)
    output_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body, encoding="utf-8")
