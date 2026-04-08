import json
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from xml.etree import ElementTree as ET

_FIELDS_TO_LABELS = {
    "title": "Title",
    "subtitle": "Subtitle",
    "composer": "Composer",
    "work_number": "Work number (e.g. Op. 45, BWV 772, K. 331)",
    "copyright": "Copyright / license",
    "tagline": "Tagline (shown at the bottom of the last page)",
}


@dataclass(frozen=True, slots=True)
class ScoreField:
    text: str = ""
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class ScoreInfo:
    title: ScoreField = field(default_factory=ScoreField)
    subtitle: ScoreField = field(default_factory=ScoreField)
    composer: ScoreField = field(default_factory=ScoreField)
    work_number: ScoreField = field(default_factory=ScoreField)
    copyright: ScoreField = field(default_factory=ScoreField)
    tagline: ScoreField = field(default_factory=ScoreField)


assert set(f.name for f in fields(ScoreInfo)) == set(_FIELDS_TO_LABELS)


def load(path: Path) -> ScoreInfo:
    data = json.loads(path.read_text())
    return ScoreInfo(**{k: ScoreField(**v) for k, v in data.items()})


def save(path: Path, info: ScoreInfo) -> None:
    path.write_text(json.dumps(asdict(info), indent=2))


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
    copyright_ = (root.findtext("identification/rights") or "").strip()
    return ScoreInfo(
        title=ScoreField(text=title),
        composer=ScoreField(text=composer),
        work_number=ScoreField(text=work_number),
        copyright=ScoreField(text=copyright_),
    )


def combine_non_interactive(cli: ScoreInfo, extracted: ScoreInfo) -> ScoreInfo:
    kwargs = {}
    for f in fields(ScoreInfo):
        cli_text = getattr(cli, f.name).text
        extracted_text = getattr(extracted, f.name).text
        text = "" if cli_text == "-" else (cli_text or extracted_text)
        confirmed = bool(cli_text)
        kwargs[f.name] = ScoreField(text=text, confirmed=confirmed)

    return ScoreInfo(**kwargs)


def collect(cli: ScoreInfo, extracted: ScoreInfo) -> ScoreInfo:
    """Prompt for fields not supplied via CLI, using OMR-extracted values as defaults."""
    result = {}
    queries = []
    for key, label in _FIELDS_TO_LABELS.items():
        cli_field = getattr(cli, key)
        if cli_field.text:
            text = "" if cli_field.text == "-" else cli_field.text
            result[key] = ScoreField(text=text, confirmed=True)
        else:
            queries.append((key, label, getattr(extracted, key).text))

    if queries:
        print("\nEnter score information (press Enter to keep the value in brackets, '-' to clear):")
        for key, label, default in queries:
            prompt = f"  {label} [{default or '<empty>'}]: "
            value = input(prompt).strip()
            result[key] = ScoreField(text="" if value == "-" else (value or default), confirmed=True)

    return ScoreInfo(**result)


def build_ly_header(info: ScoreInfo) -> str:
    """Build a LilyPond \\header block from ScoreInfo."""
    lines = ["\\header {"]
    if info.title.text:
        lines.append(f'  title = "{_ly_escape(info.title.text)}"')
    if info.subtitle.text:
        lines.append(f'  subtitle = "{_ly_escape(info.subtitle.text)}"')
    if info.composer.text:
        lines.append(f'  composer = "{_ly_escape(info.composer.text)}"')
    if info.work_number.text:
        lines.append(f'  opus = "{_ly_escape(info.work_number.text)}"')
    if info.copyright.text:
        lines.append(f'  copyright = "{_ly_escape(info.copyright.text)}"')
    if info.tagline.text:
        lines.append(f'  tagline = "{_ly_escape(info.tagline.text)}"')
    else:
        lines.append('  tagline = ##f')
    lines.append("}")
    return "\n".join(lines)


def _ly_escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')
