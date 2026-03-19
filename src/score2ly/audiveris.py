import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from score2ly.stages import Stage

logger = logging.getLogger(__name__)

_ENV_VAR = "AUDIVERIS_PATH"
_INSTALL_URL = "https://github.com/Audiveris/audiveris/releases"
_FRAUDULENT_SITE_URL = "https://audiveris.com"
_FRAUD_NOTE_URL = "https://github.com/Audiveris/audiveris?tab=readme-ov-file#beware-of-site-audiveriscom"


def find_executable() -> Path:
    path = os.environ.get(_ENV_VAR)
    if path:
        exe = Path(path)
        if exe.is_file():
            return exe
        raise RuntimeError(
            f"Audiveris not found at {_ENV_VAR}={path!r}. Check that the path is correct."
        )

    # noinspection PyDeprecation
    found = shutil.which("audiveris")
    if found:
        return Path(found)

    raise RuntimeError(
        "Audiveris not found. Install it and ensure 'audiveris' is on your PATH, "
        f"or set the {_ENV_VAR} environment variable to the executable path.\n"
        f"See: {_INSTALL_URL}\n"
        f"⚠️ Warning: Beware of the apparently fraudulent site {_FRAUDULENT_SITE_URL} (for more"
        f" information read the note in the official github repository - {_FRAUD_NOTE_URL})"
    )


def run_omr(input_pdf: Path, work_dir: Path) -> Path:
    exe = find_executable()
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [str(exe), "-batch", "-transcribe", "-save", "-output", str(work_dir), str(input_pdf)]
    logger.info("Stage %d: running Audiveris OMR on %s...", Stage.OMR, input_pdf.name)
    logger.debug("Stage %d: command: %s", Stage.OMR, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log_files = sorted(work_dir.glob("*.log"))
        log_hint = f"See log: {log_files[-1]}" if log_files else f"No log file found in {work_dir}"
        raise RuntimeError(f"Audiveris OMR failed (exit code {result.returncode}). {log_hint}")

    omr_files = sorted(work_dir.glob("*.omr"))
    if not omr_files:
        raise RuntimeError("Audiveris ran but produced no .omr output in " + str(work_dir))
    return omr_files[0]


def export_xml(omr_path: Path, work_dir: Path) -> Path:
    exe = find_executable()
    work_dir.mkdir(parents=True, exist_ok=True)

    # Audiveris ignores -output for existing .omr books and writes the export next
    # to the input file. Symlink the .omr into work_dir so output lands there.
    omr_link = work_dir / omr_path.name
    omr_link.symlink_to(omr_path.relative_to(omr_link.parent, walk_up=True))

    cmd = [str(exe), "-batch", "-export", str(omr_link)]
    logger.info("Stage %d: exporting MusicXML from %s...", Stage.MUSICXML, omr_path.name)
    logger.debug("Stage %d: command: %s", Stage.MUSICXML, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log_files = sorted(work_dir.glob("*.log"))
        log_hint = f"See log: {log_files[-1]}" if log_files else f"No log file found in {work_dir}"
        raise RuntimeError(f"Audiveris export failed (exit code {result.returncode}). {log_hint}")

    mxl_files = sorted(work_dir.glob("*.mxl"))
    xml_files = sorted(work_dir.glob("*.xml"))

    if mxl_files:
        return _extract_mxl(mxl_files[0])
    if xml_files:
        return xml_files[0]
    raise RuntimeError("Audiveris export produced no MusicXML output in " + str(work_dir))


def _extract_mxl(mxl_path: Path) -> Path:
    with zipfile.ZipFile(mxl_path) as z:
        container = ElementTree.fromstring(z.read("META-INF/container.xml"))
        root_file = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
        if root_file is None:
            root_file = container.find(".//rootfile")
        if root_file is None:
            raise RuntimeError(f"Could not find rootfile in {mxl_path}/META-INF/container.xml")

        xml_name = root_file.attrib["full-path"]
        dest = mxl_path.with_suffix(".xml")
        dest.write_bytes(z.read(xml_name))

    logger.debug("Stage %d: extracted %s from %s", Stage.MUSICXML, xml_name, mxl_path.name)
    return dest