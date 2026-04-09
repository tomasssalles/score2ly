import argparse
import logging
import shutil
import sys
from dataclasses import fields
from enum import Enum
from pathlib import Path
from importlib.metadata import version

from score2ly import pipeline, metadata
from score2ly.image_processing import BlockMethod, SheetMethod
from score2ly.pdf import PdfKind
from score2ly.settings import ConvertSettings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf"}
UNSET = object()


def main() -> None:
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    common.add_argument("--version", action="version", version=f"%(prog)s {version('score2ly')}")

    parser = argparse.ArgumentParser(
        prog="score2ly",
        description="Convert musical scores to LilyPond format.",
        parents=[common],
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command")

    settings_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    default_settings = ConvertSettings()

    def _with_default(help_str: str, arg_name: str) -> str:
        default_value = getattr(default_settings, arg_name)
        if issubclass(type(default_value), Enum):
            default_value = default_value.value
        return f"{help_str} (default: {default_value!r})"

    score = settings_parser.add_argument_group("score information")
    score.add_argument("--title", default=UNSET, help=_with_default("Score title ('-' to leave blank)", "title"))
    score.add_argument("--subtitle", default=UNSET, help=_with_default("Score subtitle ('-' to leave blank)", "subtitle"))
    score.add_argument("--composer", default=UNSET, help=_with_default("Composer name ('-' to leave blank)", "composer"))
    score.add_argument("--work-number", default=UNSET, help=_with_default("Work number (e.g. Op. 45, BWV 772, K. 331) ('-' to leave blank)", "work_number"))
    score.add_argument("--copyright", default=UNSET, help=_with_default("Copyright or license statement ('-' to leave blank)", "copyright"))
    score.add_argument("--tagline", default=UNSET, help=_with_default("Tagline shown at the bottom of the last page ('-' to leave blank)", "tagline"))
    score.add_argument("--no-prompt", default=UNSET, action="store_true", help=_with_default("Skip interactive score information prompts and just use OMR-extracted values and any CLI args provided", "no_prompt"))

    advanced = settings_parser.add_argument_group("advanced")
    advanced.add_argument("--pdf-kind", default=UNSET, choices=[k.value for k in PdfKind], help=_with_default("Override PDF type detection", "pdf_kind"))
    advanced.add_argument("--sheet-method", default=UNSET, choices=[m.value for m in SheetMethod], help=_with_default("Page isolation method", "sheet_method"))
    advanced.add_argument("--block-method", default=UNSET, choices=[m.value for m in BlockMethod], help=_with_default("Music block detection method", "block_method"))
    advanced.add_argument("--deskew", default=UNSET, action="store_true", help=_with_default("Enable deskew step", "deskew"))
    advanced.add_argument("--tight-crop", default=UNSET, action="store_true", help=_with_default("Enable tight crop step", "tight_crop"))
    advanced.add_argument("--clahe", default=UNSET, action="store_true", help=_with_default("Enable CLAHE contrast enhancement", "clahe"))
    advanced.add_argument("--projection-k", default=UNSET, type=float, metavar="K", help=_with_default("Ink threshold = mean - K*std for projection method", "projection_k"))
    advanced.add_argument("--projection-denoise", default=UNSET, action="store_true", help=_with_default("Enable morphological denoising in projection step", "projection_denoise"))

    # convert subcommand
    convert = subparsers.add_parser("convert", parents=[common, settings_parser], help="Convert a score file into a new .s2l bundle.")
    convert.set_defaults(func=_convert)

    convert.add_argument("input", type=Path, help="Input score file")
    output_group = convert.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", type=Path, help="Full output path (must end in .s2l)")
    output_group.add_argument("-d", "--directory", type=Path, help="Parent directory for output (bundle name is derived automatically) (default: input file's directory)")
    convert.add_argument("--overwrite", action="store_true", help="Overwrite existing output bundle without prompting (error if it doesn't exist)")

    # update subcommand
    update = subparsers.add_parser("update", parents=[common, settings_parser], help="Resume the pipeline from a .s2l bundle after manual edits.")
    update.set_defaults(func=_update)

    update.add_argument("bundle", type=Path, help="Path to the .s2l bundle directory")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


def _convert(args: argparse.Namespace) -> None:
    input_path = args.input
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        logger.error(
            "Unsupported input format '%s'. Supported: %s",
            input_path.suffix,
            sorted(SUPPORTED_EXTENSIONS),
        )
        sys.exit(1)

    if args.output is not None:
        if args.output.suffix != ".s2l":
            logger.error("Output path must end in .s2l: %s", args.output)
            sys.exit(1)
        output_dir = args.output
    elif args.directory is not None:
        if not args.directory.is_dir():
            logger.error("Directory not found: %s", args.directory)
            sys.exit(1)
        output_dir = args.directory / input_path.with_suffix(".s2l").name
    else:
        output_dir = input_path.with_suffix(".s2l")

    if args.overwrite:
        if not output_dir.exists():
            logger.error("--overwrite specified but output does not exist: %s", output_dir)
            sys.exit(1)
        shutil.rmtree(output_dir)
    elif output_dir.exists():
        answer = input(f"Output directory '{output_dir}' already exists. Overwrite? [y/N] ")
        if answer.strip().lower() != "y":
            logger.info("Aborted.")
            sys.exit(0)
        shutil.rmtree(output_dir)

    output_dir.mkdir()

    logger.info("Processing: %s", input_path)
    logger.info("Output directory: %s", output_dir)
    metadata.create(output_dir, sys.argv, Path.cwd(), input_path)
    _run_pipeline(input_path, output_dir, args)


def _update(args: argparse.Namespace) -> None:
    output_dir = args.bundle
    if not output_dir.is_dir():
        logger.error("Bundle directory not found: %s", output_dir)
        sys.exit(1)
    if output_dir.suffix != ".s2l":
        logger.error("Bundle path must end in .s2l: %s", output_dir)
        sys.exit(1)
    if not (output_dir / metadata.METADATA_FILENAME).exists():
        logger.error("No metadata file found in bundle: %s", output_dir)
        sys.exit(1)

    maybe_ignored_args = [f.name for f in fields(ConvertSettings) if getattr(args, f.name, UNSET) is not UNSET]
    if maybe_ignored_args:
        print()
        logger.warning(
            "Some of the used commandline args may be ignored if the stages that need them are already done: %r",
            maybe_ignored_args,
        )
        print()

    logger.info("Updating bundle: %s", output_dir)
    _run_pipeline(None, output_dir, args)


def _run_pipeline(input_path: Path | None, output_dir: Path, args: argparse.Namespace) -> None:
    settings_kwargs = {}
    for field in fields(ConvertSettings):
        name = field.name
        value = getattr(args, name, UNSET)

        if value is UNSET:
            continue

        if name == "pdf_kind":
            value = PdfKind(value)
        elif name == "sheet_method":
            value = SheetMethod(value)
        elif name == "block_method":
            value = BlockMethod(value)

        settings_kwargs[name] = value

    settings = ConvertSettings(**settings_kwargs)

    try:
        pipeline.run(input_path, output_dir, settings)
    except ValueError:
        logger.exception("Oops, something went wrong.")
        sys.exit(2)