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


def _run_audiveris(extra_args: list[str], work_dir: Path, stage: int, identifier: str) -> None:
    exe = find_executable()
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [str(exe), "-batch", "-output", str(work_dir), *extra_args]
    logger.debug("Stage %d: Command: %s", stage, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log_files = sorted(work_dir.glob("*.log"))
        log_hint = f"See log: {log_files[-1]}" if log_files else f"No log file found in {work_dir}"
        raise RuntimeError(f"Audiveris {identifier} failed (exit code {result.returncode}). {log_hint}")


def run_omr(input_path: Path, work_dir: Path, stage: int) -> Path:
    logger.info("Stage %d: Running Audiveris OMR on %s...", stage, input_path.name)
    _run_audiveris(["-transcribe", "-save", str(input_path)], work_dir, stage, "OMR transcription")

    expected = work_dir / f"{input_path.stem}.omr"
    if not expected.exists():
        raise RuntimeError(f"Audiveris ran but produced no .omr output at {expected}")

    logger.info("Stage %d: Finished OMR run %s -> %s", stage, input_path.name, expected.name)
    return expected


def export_xml(omr_path: Path, work_dir: Path, stage: int) -> Path:
    # Audiveris ignores -output for existing .omr books and writes the export next
    # to the input file. Symlink the .omr into work_dir so output lands there.
    omr_link = work_dir / omr_path.name
    work_dir.mkdir(parents=True, exist_ok=True)
    omr_link.symlink_to(omr_path.relative_to(omr_link.parent, walk_up=True))

    logger.info("Stage %d: Exporting MusicXML from %s...", stage, omr_path.name)
    extra_args = ["-export", "-constant", "org.audiveris.omr.sheet.BookManager.useCompression=false", str(omr_link)]
    _run_audiveris(extra_args, work_dir, stage, "MusicXML export")

    expected = omr_link.with_suffix(".xml")
    if not expected.exists():
        mvt_files = sorted(work_dir.glob(f"{omr_link.stem}.mvt*.xml"))
        if mvt_files:
            raise RuntimeError(
                f"Multi-movement scores are not yet supported. "
                f"Audiveris exported {len(mvt_files)} movement file(s): "
                + ", ".join(f.name for f in mvt_files)
            )
        raise RuntimeError(f"Audiveris export did not produce the expected XML output file {expected}")
    return expected
