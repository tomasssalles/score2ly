import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

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


def run(input_images: list[Path], work_dir: Path) -> Path:
    exe = find_executable()
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [str(exe), "-batch", "-export", "-output", str(work_dir), *[str(p) for p in input_images]]
    logger.info("Stage 3: running Audiveris on %d page(s)...", len(input_images))
    logger.debug("Stage 3: command: %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Audiveris failed (exit code {result.returncode}):\n{result.stderr}"
        )

    mxl_files = sorted(work_dir.glob("*.mxl"))
    xml_files = sorted(work_dir.glob("*.xml"))

    if mxl_files:
        return _extract_mxl(mxl_files[0])
    if xml_files:
        return xml_files[0]
    raise RuntimeError("Audiveris ran but produced no MusicXML output in " + str(work_dir))


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

    logger.debug("Stage 3: extracted %s from %s", xml_name, mxl_path.name)
    return dest
