import copy
from collections.abc import Sequence, Iterable
from pathlib import Path
from xml.etree import ElementTree

from score2ly.musicxml_cleanup import inject_missing_attrs

_CARRY_FORWARD_TAGS = frozenset({"divisions", "time", "key", "clef"})


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

    sorted_systems, sys_ranges = _sort_and_validate(systems)

    # Single pass per part: collect system measures and track attribute carry-forward.
    # per_system_measures[sys_i][part_id] = list of measure Elements (not yet copied)
    # system_carried[sys_i][part_id] = carried attrs dict for that part before that system
    per_system_measures: list[dict[str, list]] = [{} for _ in sorted_systems]
    system_carried: list[dict[str, dict]] = [{} for _ in sorted_systems]

    for part in parts:
        part_id = part.attrib["id"]
        measure_iter = iter(part.findall("measure"))
        current_attrs: dict = {}
        prev_last: int | None = None

        for sys_i, (system, (first_num, last_num)) in enumerate(zip(sorted_systems, sys_ranges)):
            # Advance past any gap between previous system and this one, collecting attrs
            gap_start = prev_last + 1 if prev_last is not None else first_num
            for gap_num in range(gap_start, first_num):
                m = next(measure_iter)
                if int(m.attrib["number"]) != gap_num:
                    raise ValueError(
                        f"Part {part_id}: expected measure {gap_num}, got {m.attrib['number']}"
                    )
                _update_attrs(current_attrs, m)

            system_carried[sys_i][part_id] = dict(current_attrs)

            measures = []
            for expected_num in range(first_num, last_num + 1):
                m = next(measure_iter)
                if int(m.attrib["number"]) != expected_num:
                    raise ValueError(
                        f"Part {part_id}: expected measure {expected_num}, got {m.attrib['number']}"
                    )
                _update_attrs(current_attrs, m)
                measures.append(m)

            per_system_measures[sys_i][part_id] = measures
            prev_last = last_num

    # Write snippets
    for sys_i, system in enumerate(sorted_systems):
        carried_by_part = system_carried[sys_i]
        first_num = sys_ranges[sys_i][0]

        sys_path = systems_dir / f"system_{system['global_id']:04d}.xml"
        _write_snippet(root, part_list, parts, per_system_measures[sys_i], sys_path, carried_by_part)
        yield sys_path

        for m_info in system["measures"]:
            idx = m_info["global_id"] - first_num
            single = {pid: [measures[idx]] for pid, measures in per_system_measures[sys_i].items()}
            meas_path = measures_dir / f"measure_{m_info['global_id']:04d}.xml"
            _write_snippet(root, part_list, parts, single, meas_path, carried_by_part)
            yield meas_path


def _sort_and_validate(systems: Sequence[dict]) -> tuple[list[dict], list[tuple[int, int]]]:
    def get_range(s: dict) -> tuple[int, int]:
        nums = sorted(m["global_id"] for m in s["measures"])
        if nums != list(range(nums[0], nums[-1] + 1)):
            raise ValueError(f"System {s['global_id']} has non-contiguous measures: {nums}")
        return nums[0], nums[-1]

    sorted_s = sorted(systems, key=lambda s: min(m["global_id"] for m in s["measures"]))
    ranges = [get_range(s) for s in sorted_s]
    return sorted_s, ranges


def _update_attrs(current: dict, measure: ElementTree.Element) -> None:
    for attrs_el in measure.findall("attributes"):
        for child in attrs_el:
            if child.tag in _CARRY_FORWARD_TAGS:
                current[(child.tag, child.attrib.get("number"))] = child


def _write_snippet(
    root: ElementTree.Element,
    part_list: ElementTree.Element,
    parts: list[ElementTree.Element],
    measures_by_part_id: dict[str, list[ElementTree.Element]],
    output_path: Path,
    carried_by_part: dict[str, dict] | None = None,
) -> None:
    new_root = ElementTree.Element("score-partwise")
    if "version" in root.attrib:
        new_root.set("version", root.attrib["version"])
    new_root.append(copy.deepcopy(part_list))

    for part in parts:
        part_id = part.attrib["id"]
        new_part = ElementTree.SubElement(new_root, "part")
        new_part.set("id", part_id)
        carried = (carried_by_part or {}).get(part_id)
        for i, m in enumerate(measures_by_part_id[part_id]):
            m_copy = copy.deepcopy(m)
            if i == 0 and carried:
                inject_missing_attrs(m_copy, carried)
            new_part.append(m_copy)

    ElementTree.indent(new_root, space="  ")
    xml_body = ElementTree.tostring(new_root, encoding="unicode", xml_declaration=False)
    output_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body, encoding="utf-8")
