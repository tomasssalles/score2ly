import logging
import os
import shutil
import subprocess
from pathlib import Path

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

    xml_files = sorted(work_dir.glob("*.mxl")) + sorted(work_dir.glob("*.xml"))
    if not xml_files:
        raise RuntimeError("Audiveris ran but produced no MusicXML output in " + str(work_dir))

    return xml_files[0]
