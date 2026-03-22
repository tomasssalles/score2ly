import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_VAR = "MUSICXML2LY_PATH"
_INSTALL_URL = "https://lilypond.org/download.html"


def find_executable() -> Path:
    path = os.environ.get(_ENV_VAR)
    if path:
        exe = Path(path)
        if exe.is_file():
            return exe
        raise RuntimeError(
            f"musicxml2ly not found at {_ENV_VAR}={path!r}. Check that the path is correct."
        )

    # noinspection PyDeprecation
    found = shutil.which("musicxml2ly")
    if found:
        return Path(found)

    raise RuntimeError(
        "musicxml2ly not found. Install LilyPond and ensure 'musicxml2ly' is on your PATH, "
        f"or set the {_ENV_VAR} environment variable to the executable path.\n"
        f"See: {_INSTALL_URL}"
    )


def run(input_xml: Path, output_ly: Path, stage: int) -> None:
    exe = find_executable()

    cmd = [str(exe), str(input_xml), "-o", str(output_ly)]
    logger.info("Stage %d: Converting MusicXML to LilyPond...", stage)
    logger.debug("Stage %d: Command: %s", stage, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"musicxml2ly failed (exit code {result.returncode}).\n{result.stderr.strip()}"
        )

    if not output_ly.exists():
        raise RuntimeError(f"musicxml2ly ran but produced no output at {output_ly}")
