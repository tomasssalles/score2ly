import argparse
import logging
import shutil
import sys
from pathlib import Path
from importlib.metadata import version

from score2ly import pipeline, metadata
from score2ly.image_processing import (
    BlockMethod,
    SheetMethod,
    DEFAULT_PROJECTION_K,
    DEFAULT_SHEET_METHOD,
    DEFAULT_BLOCK_METHOD,
)
from score2ly.settings import ConvertSettings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf"}


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    parser = argparse.ArgumentParser(
        prog="score2ly",
        description="Convert musical scores to LilyPond format.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('score2ly')}")

    subparsers = parser.add_subparsers(dest="command")

    # convert subcommand
    convert = subparsers.add_parser("convert", parents=[common], help="Convert a score file into a new .s2l bundle.")
    convert.add_argument("input", type=Path, help="Input score file")
    output_group = convert.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", type=Path, help="Full output path (must end in .s2l)")
    output_group.add_argument("-d", "--directory", type=Path, help="Parent directory for output (default: input file's directory)")
    convert.add_argument("--overwrite", action="store_true", help="Overwrite existing output bundle without prompting (error if it doesn't exist)")

    advanced = convert.add_argument_group("advanced")
    advanced.add_argument("--pdf-kind", choices=["auto", "scan", "vector"], default="auto",
                          help="Override PDF type detection (default: auto)")
    advanced.add_argument("--sheet-method", choices=[m.value for m in SheetMethod], default=DEFAULT_SHEET_METHOD.value,
                          help=f"Page isolation method (default: {DEFAULT_SHEET_METHOD.value})")
    advanced.add_argument("--block-method", choices=[m.value for m in BlockMethod], default=DEFAULT_BLOCK_METHOD.value,
                          help=f"Music block detection method (default: {DEFAULT_BLOCK_METHOD.value})")
    advanced.add_argument("--deskew", action="store_true", help="Enable deskew step")
    advanced.add_argument("--tight-crop", action="store_true", help="Enable tight crop step")
    advanced.add_argument("--clahe", action="store_true", help="Enable CLAHE contrast enhancement")
    advanced.add_argument("--projection-k", type=float, default=DEFAULT_PROJECTION_K, metavar="K",
                          help=f"Ink threshold = mean - K*std for projection method (default: {DEFAULT_PROJECTION_K})")
    advanced.add_argument("--projection-denoise", action="store_true",
                          help="Enable morphological denoising in projection step")

    # update subcommand
    update = subparsers.add_parser("update", parents=[common], help="Resume the pipeline from a .s2l bundle after manual edits.")
    update.add_argument("bundle", type=Path, help="Path to the .s2l bundle directory")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

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

    if args.overwrite:
        if not output.exists():
            logger.error("--overwrite specified but output does not exist: %s", output)
            sys.exit(1)
        shutil.rmtree(output)
    elif output.exists():
        answer = input(f"Output directory '{output}' already exists. Overwrite? [y/N] ")
        if answer.strip().lower() != "y":
            logger.info("Aborted.")
            sys.exit(0)
        shutil.rmtree(output)

    settings = ConvertSettings(
        pdf_kind=args.pdf_kind,
        sheet_method=SheetMethod(args.sheet_method),
        block_method=BlockMethod(args.block_method),
        deskew=args.deskew,
        tight_crop=args.tight_crop,
        clahe=args.clahe,
        projection_k=args.projection_k,
        projection_denoise=args.projection_denoise,
    )

    output.mkdir()
    logger.info("Processing: %s", args.input)
    logger.info("Output directory: %s", output)

    metadata.create(output, sys.argv, Path.cwd(), args.input)
    _run_pipeline(args.input, output, settings)


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


def _run_pipeline(input_path: Path | None, output_dir: Path, settings: ConvertSettings | None = None) -> None:
    try:
        pipeline.run(input_path, output_dir, settings)
    except ValueError:
        logger.exception("Oops, something went wrong.")
        sys.exit(2)