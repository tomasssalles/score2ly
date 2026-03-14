import argparse
import logging
import shutil
import sys
from pathlib import Path
from importlib.metadata import version

from score2ly import pipeline, metadata

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf"}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        prog="score2ly",
        description="Convert musical scores to LilyPond format.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('score2ly')}")

    subparsers = parser.add_subparsers(dest="command")

    # convert subcommand
    convert = subparsers.add_parser("convert", help="Convert a score file into a new .s2l bundle.")
    convert.add_argument("input", type=Path, help="Input score file")
    output_group = convert.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", type=Path, help="Full output path (must end in .s2l)")
    output_group.add_argument("-d", "--directory", type=Path, help="Parent directory for output (default: input file's directory)")

    # update subcommand
    update = subparsers.add_parser("update", help="Resume the pipeline from a .s2l bundle after manual edits.")
    update.add_argument("bundle", type=Path, help="Path to the .s2l bundle directory")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "convert":
        _convert(args)
    elif args.command == "update":
        _update(args)


def _convert(args: argparse.Namespace) -> None:
    if not args.input.exists():
        logger.error("Input file not found: %s", args.input)
        sys.exit(1)

    if args.input.suffix.lower() not in SUPPORTED_EXTENSIONS:
        logger.error(
            "Unsupported input format '%s'. Supported: %s",
            args.input.suffix,
            sorted(SUPPORTED_EXTENSIONS),
        )
        sys.exit(1)

    if args.output is not None:
        if args.output.suffix != ".s2l":
            logger.error("Output path must end in .s2l: %s", args.output)
            sys.exit(1)
        output = args.output
    elif args.directory is not None:
        if not args.directory.is_dir():
            logger.error("Directory not found: %s", args.directory)
            sys.exit(1)
        output = args.directory / args.input.with_suffix(".s2l").name
    else:
        output = args.input.with_suffix(".s2l")

    if output.exists():
        answer = input(f"Output directory '{output}' already exists. Overwrite? [y/N] ")
        if answer.strip().lower() != "y":
            logger.info("Aborted.")
            sys.exit(0)
        shutil.rmtree(output)

    output.mkdir()
    logger.info("Processing: %s", args.input)
    logger.info("Output directory: %s", output)

    metadata.create(output, sys.argv, Path.cwd(), args.input)
    _run_pipeline(args.input, output)


def _update(args: argparse.Namespace) -> None:
    bundle = args.bundle
    if not bundle.is_dir():
        logger.error("Bundle directory not found: %s", bundle)
        sys.exit(1)
    if bundle.suffix != ".s2l":
        logger.error("Bundle path must end in .s2l: %s", bundle)
        sys.exit(1)
    if not (bundle / metadata.METADATA_FILENAME).exists():
        logger.error("No metadata file found in bundle: %s", bundle)
        sys.exit(1)

    logger.info("Updating bundle: %s", bundle)
    _run_pipeline(None, bundle)


def _run_pipeline(input_path: Path | None, output_dir: Path) -> None:
    try:
        pipeline.run(input_path, output_dir)
    except ValueError:
        logger.exception("Oops, something went wrong.")
        sys.exit(2)