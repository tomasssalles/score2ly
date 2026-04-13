import logging
import os
import shutil
import subprocess
from pathlib import Path

from score2ly.exceptions import PipelineError

logger = logging.getLogger(__name__)

_ENV_VAR = "LILYPOND_PATH"
_INSTALL_URL = "https://lilypond.org/download.html"


def find_executable() -> Path:
    path = os.environ.get(_ENV_VAR)
    if path:
        exe = Path(path)
        if exe.is_file():
            return exe
        raise PipelineError(
            f"LilyPond not found at {_ENV_VAR}={path!r}. Check that the path is correct."
        )

    found = shutil.which("lilypond")
    if found:
        return Path(found)

    raise PipelineError(
        "LilyPond not found. Install it and ensure 'lilypond' is on your PATH, "
        f"or set the {_ENV_VAR} environment variable to the executable path.\n"
        f"See: {_INSTALL_URL}"
    )


def render(input_ly: Path, output_pdf: Path, stage: int) -> None:
    exe = find_executable()

    # LilyPond appends .pdf to the output prefix, so strip it
    output_prefix = output_pdf.with_suffix("")

    cmd = [str(exe), "-o", str(output_prefix), str(input_ly)]
    logger.info("Stage %d: Rendering LilyPond to PDF...", stage)
    logger.debug("Stage %d: Command: %s", stage, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PipelineError(
            f"LilyPond failed (exit code {result.returncode}).\n{result.stderr.strip()}"
        )

    if not output_pdf.exists():
        raise PipelineError(f"LilyPond ran but produced no PDF at {output_pdf}")