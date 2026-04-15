import argparse
import logging
import shutil
import sys
from collections.abc import Iterator, Callable
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from importlib.metadata import version
from typing import Any

from score2ly import config_utils, metadata, convert_pipeline, fix_pipeline
from score2ly.exceptions import PipelineError
from score2ly.image_processing import BlockMethod, SheetMethod
from score2ly.pdf import PdfKind
from score2ly.settings import ConvertSettings, DEFAULT_MAX_RETRIES, FixSettings
from score2ly.utils import APIKey

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf"}


def _parse_page_range(s: str) -> tuple[int, int]:
    parts = s.split("-")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"Expected format START-END (e.g. '5-9'), got: {s!r}")
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(f"Page numbers must be integers, got: {s!r}")
    if start < 1:
        raise argparse.ArgumentTypeError(f"Start page must be >= 1, got: {start}")
    if end < start:
        raise argparse.ArgumentTypeError(f"End page must be >= start ({start}), got: {end}")
    return (start, end)


def _validate_xml_path(path: Path) -> None:
    if not path.exists():
        logger.error("XML file not found: %s", path)
        sys.exit(1)
    if path.suffix.lower() != ".xml":
        logger.error("Expected a .xml file, got: %s", path)
        sys.exit(1)


UNSET = object()

_LEVEL_COLORS = {
    logging.DEBUG:    "\033[2m",    # dim
    logging.INFO:     "\033[32m",   # green
    logging.WARNING:  "\033[33m",   # yellow
    logging.ERROR:    "\033[31m",   # red
    logging.CRITICAL: "\033[1;31m", # bold red
}
_RESET = "\033[0m"


class _TimestampFormatter(logging.Formatter):
    def __init__(self, fmt: str) -> None:
        super().__init__(fmt)
        self._use_color = sys.stderr.isatty()

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created).astimezone()

        if not dt.strftime("%Z"):
            dt = datetime.fromtimestamp(record.created, tz=timezone.utc)

        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")

    def format(self, record):
        msg = super().format(record)

        if not self._use_color:
            return msg

        color = _LEVEL_COLORS.get(record.levelno, "")
        if color and msg.startswith("["):
            if record.levelno == logging.DEBUG:
                reset_pos = len(msg)
            else:
                reset_pos = msg.index("]") + 1
            return f"{color}{msg[:reset_pos]}{_RESET}{msg[reset_pos:]}"

        return msg


def _with_default(help_str: str, arg_name: str, defaults: Any) -> str:
    default_value = getattr(defaults, arg_name)
    if issubclass(type(default_value), Enum):
        default_value = default_value.value
    return f"{help_str} (default: {default_value!r})"


def _add_parser(
    subparsers, name: str, help_text: str, func: Callable[[argparse.Namespace], None], **kwargs
) -> argparse.ArgumentParser:
    p = subparsers.add_parser(name, help=help_text, description=help_text, **kwargs)
    p.set_defaults(print_help=p.print_help, func=func)
    return p


def _config(args: argparse.Namespace) -> None:
    args.print_help()
    sys.exit(1)


def _config_list(args: argparse.Namespace) -> None:
    cfg = config_utils.load()
    path = config_utils.CONFIG_PATH
    print(f"Config file: {path}{'' if path.exists() else ' (not found)'}")
    print()
    print(f"  default_model  {cfg.default_model or '(not set)'}")
    if cfg.max_retries is not None:
        print(f"  max_retries    {cfg.max_retries}")
    else:
        print(f"  max_retries    (not set, default: {DEFAULT_MAX_RETRIES})")
    if cfg.api_keys:
        print("  api_keys:")
        for provider, key in cfg.api_keys.items():
            print(f"    {provider:<16}{key}")
    else:
        print("  api_keys       (none)")


def _config_set(args: argparse.Namespace) -> None:
    if args.default_model is None and args.max_retries is None and args.api_key is None:
        args.print_help()
        sys.exit(1)

    with _error_handling(args.verbose):
        cfg = config_utils.load(strict=True)

    if args.default_model is not None:
        cfg = replace(cfg, default_model=args.default_model)

    if args.max_retries is not None:
        cfg = replace(cfg, max_retries=args.max_retries)

    if args.api_key is not None:
        provider, key = args.api_key
        cfg = replace(cfg, api_keys={**cfg.api_keys, provider.lower(): APIKey(key)})

    config_utils.save(cfg)
    logger.info("Config saved to %s", config_utils.CONFIG_PATH)


def _config_unset(args: argparse.Namespace) -> None:
    if not args.default_model and not args.max_retries and args.api_key is None:
        args.print_help()
        sys.exit(1)

    with _error_handling(args.verbose):
        cfg = config_utils.load(strict=True)

    if args.default_model:
        cfg = replace(cfg, default_model="")

    if args.max_retries:
        cfg = replace(cfg, max_retries=None)

    if args.api_key is not None:
        provider = args.api_key.lower()
        new_api_keys = {k: v for k, v in cfg.api_keys.items() if k != provider}
        if len(new_api_keys) == len(cfg.api_keys):
            logger.warning("No API key found for %r", args.api_key)
        cfg = replace(cfg, api_keys=new_api_keys)

    config_utils.save(cfg)
    logger.info("Config saved to %s", config_utils.CONFIG_PATH)


def _config_path(args: argparse.Namespace) -> None:
    if not config_utils.CONFIG_PATH.exists():
        config_utils.save(config_utils.AppConfig())

    print(config_utils.CONFIG_PATH)


def main() -> None:
    common_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common_parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    common_parser.add_argument("--version", action="version", version=f"%(prog)s {version('score2ly')}")

    parser = argparse.ArgumentParser(
        prog="score2ly",
        description="Convert musical scores to LilyPond format.",
        parents=[common_parser],
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", title="subcommands")

    conv_settings_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    default_conv_settings = ConvertSettings()

    score_info_group = conv_settings_parser.add_argument_group("score information")
    score_info_group.add_argument("--title", default=UNSET, help=_with_default("Score title ('-' to leave blank)", "title", default_conv_settings))
    score_info_group.add_argument("--subtitle", default=UNSET, help=_with_default("Score subtitle ('-' to leave blank)", "subtitle", default_conv_settings))
    score_info_group.add_argument("--composer", default=UNSET, help=_with_default("Composer name ('-' to leave blank)", "composer", default_conv_settings))
    score_info_group.add_argument("--work-number", default=UNSET, help=_with_default("Work number (e.g. Op. 45, BWV 772, K. 331) ('-' to leave blank)", "work_number", default_conv_settings))
    score_info_group.add_argument("--copyright", default=UNSET, help=_with_default("Copyright or license statement ('-' to leave blank)", "copyright", default_conv_settings))
    score_info_group.add_argument("--tagline", default=UNSET, help=_with_default("Tagline shown at the bottom of the last page ('-' to leave blank)", "tagline", default_conv_settings))
    score_info_group.add_argument("--no-prompt", default=UNSET, action="store_true", help=_with_default("Skip interactive score information prompts and just use OMR-extracted values and any CLI args provided", "no_prompt", default_conv_settings))

    advanced_pp_group = conv_settings_parser.add_argument_group("advanced image preprocessing")
    advanced_pp_group.add_argument("--pdf-kind", default=UNSET, choices=[k.value for k in PdfKind], help=_with_default("Override PDF type detection", "pdf_kind", default_conv_settings))
    advanced_pp_group.add_argument("--sheet-method", default=UNSET, choices=[m.value for m in SheetMethod], help=_with_default("Page isolation method", "sheet_method", default_conv_settings))
    advanced_pp_group.add_argument("--block-method", default=UNSET, choices=[m.value for m in BlockMethod], help=_with_default("Music block detection method", "block_method", default_conv_settings))
    advanced_pp_group.add_argument("--background-normalize", default=UNSET, action="store_true", help=_with_default("Enable background normalization (division)", "background_normalize", default_conv_settings))
    advanced_pp_group.add_argument("--background-normalize-kernel", default=UNSET, type=float, metavar="F", help=_with_default("Kernel size as a fraction of page width for background estimation", "background_normalize_kernel", default_conv_settings))
    advanced_pp_group.add_argument("--trunc-threshold", default=UNSET, action="store_true", help=_with_default("Enable truncated thresholding (ceiling method)", "trunc_threshold", default_conv_settings))
    advanced_pp_group.add_argument("--trunc-threshold-value", default=UNSET, type=int, metavar="V", help=_with_default("Pixels at or above this value are set to white (0–255)", "trunc_threshold_value", default_conv_settings))
    advanced_pp_group.add_argument("--gamma-correction", default=UNSET, action="store_true", help=_with_default("Enable gamma correction (dark-weighted suppression)", "gamma_correction", default_conv_settings))
    advanced_pp_group.add_argument("--gamma", default=UNSET, type=float, metavar="G", help=_with_default("Gamma value for correction (suggested range 1.5–3.0)", "gamma", default_conv_settings))
    advanced_pp_group.add_argument("--deskew", default=UNSET, action="store_true", help=_with_default("Enable deskew step", "deskew", default_conv_settings))
    advanced_pp_group.add_argument("--tight-crop", default=UNSET, action="store_true", help=_with_default("Enable tight crop step", "tight_crop", default_conv_settings))
    advanced_pp_group.add_argument("--clahe", default=UNSET, action="store_true", help=_with_default("Enable CLAHE contrast enhancement", "clahe", default_conv_settings))
    advanced_pp_group.add_argument("--projection-k", default=UNSET, type=float, metavar="K", help=_with_default("Ink threshold = mean - K*std for projection method", "projection_k", default_conv_settings))
    advanced_pp_group.add_argument("--projection-denoise", default=UNSET, action="store_true", help=_with_default("Enable morphological denoising in projection step", "projection_denoise", default_conv_settings))

    xml_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    xml_parser.add_argument("--xml", type=Path, default=None, metavar="FILE", help="Use this MusicXML file instead of running Audiveris OMR export")

    fix_settings_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    default_fix_settings = FixSettings(max_retries=DEFAULT_MAX_RETRIES)

    llm_group = fix_settings_parser.add_argument_group("LLM parameters")
    llm_group.add_argument("--model", default=UNSET, metavar="MODEL", help="LLM model to use (e.g. gemini/gemini-2.5-flash); prompted if not provided")
    llm_group.add_argument("--api-key", default=UNSET, type=APIKey, metavar="KEY", help="API key for the LLM provider; prompted if not provided (pass '-' to use cached requests only)")
    llm_group.add_argument("--max-retries", default=UNSET, type=int, metavar="N", help=_with_default("Maximum number of instructor retries on schema validation failure", "max_retries", default_fix_settings))

    # 'new' subcommand
    new = _add_parser(subparsers, "new", "Create a new .s2l bundle from a score file.", func=_new, parents=[common_parser, conv_settings_parser, xml_parser])

    new.add_argument("input_pdf", type=Path, help="Input score file")
    output_group = new.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", type=Path, help="Full output path (must end in .s2l)")
    output_group.add_argument("-d", "--directory", type=Path, help="Parent directory for output (bundle name is derived automatically) (default: input file's directory)")
    new.add_argument("--overwrite", action="store_true", help="Overwrite existing output bundle without prompting (error if it doesn't exist)")
    new.add_argument("--page-range", type=_parse_page_range, default=None, metavar="START-END", help="Only convert pages START through END (1-indexed, inclusive)")

    # 'update' subcommand
    update = _add_parser(subparsers, "update", "Partially re-run the pipeline on a .s2l bundle after manual edits.", func=_update, parents=[common_parser, conv_settings_parser, xml_parser])

    update.add_argument("bundle", type=Path, help="Path to the .s2l bundle directory")

    # 'fix' subcommand
    fix = _add_parser(subparsers, "fix", "Fix OMR mistakes with an LLM.", func=_fix, parents=[common_parser, fix_settings_parser])

    fix.add_argument("bundle", type=Path, help="Path to the .s2l bundle directory")

    # 'config' subcommand
    config_parser = _add_parser(subparsers, "config", "Manage score2ly configuration.", func=_config, parents=[common_parser])
    config_subparsers = config_parser.add_subparsers(dest="config_command", title="subcommands")

    _add_parser(config_subparsers, "list", "Show current configuration values.", func=_config_list, parents=[common_parser])

    config_set_parser = _add_parser(config_subparsers, "set", "Set one or more configuration values.", func=_config_set, parents=[common_parser])
    config_set_parser.add_argument("--default-model", metavar="MODEL", default=None, help="Default LLM model (e.g. gemini/gemini-2.5-flash).")
    config_set_parser.add_argument("--max-retries", type=int, metavar="N", default=None, help=f"Max instructor retries on schema validation failure (default: {DEFAULT_MAX_RETRIES}).")
    config_set_parser.add_argument("--api-key", nargs=2, metavar=("PROVIDER_OR_MODEL", "KEY"), default=None, help="Set API key for a provider or model (e.g. --api-key gemini AIzaSy...).")

    config_unset_parser = _add_parser(config_subparsers, "unset", "Unset one or more configuration values.", func=_config_unset, parents=[common_parser])
    config_unset_parser.add_argument("--default-model", action="store_true", default=False, help="Unset the default model.")
    config_unset_parser.add_argument("--max-retries", action="store_true", default=False, help="Unset max retries (reverts to built-in default).")
    config_unset_parser.add_argument("--api-key", metavar="PROVIDER_OR_MODEL", default=None, help="Remove API key for a provider or model.")

    _add_parser(config_subparsers, "path", "Print the path to the config file.", func=_config_path, parents=[common_parser])

    args = parser.parse_args()

    handler = logging.StreamHandler()
    handler.setFormatter(_TimestampFormatter("[%(levelname)s - %(asctime)s] %(message)s"))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=[handler])
    logging.getLogger("PIL").setLevel(logging.INFO)
    logging.getLogger("img2pdf").setLevel(logging.INFO)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


def _new(args: argparse.Namespace) -> None:
    input_pdf_path = args.input_pdf
    if not input_pdf_path.exists():
        logger.error("Input file not found: %s", input_pdf_path)
        sys.exit(1)

    if input_pdf_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        logger.error(
            "Unsupported input format '%s'. Supported: %s",
            input_pdf_path.suffix,
            sorted(SUPPORTED_EXTENSIONS),
        )
        sys.exit(1)

    input_xml_path = args.xml
    if input_xml_path is not None:
        _validate_xml_path(input_xml_path)

    if args.output is not None:
        if args.output.suffix != ".s2l":
            logger.error("Output path must end in .s2l: %s", args.output)
            sys.exit(1)
        output_dir = args.output
    elif args.directory is not None:
        if not args.directory.is_dir():
            logger.error("Directory not found: %s", args.directory)
            sys.exit(1)
        output_dir = args.directory / input_pdf_path.with_suffix(".s2l").name
    else:
        output_dir = input_pdf_path.with_suffix(".s2l")

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

    logger.info("Processing: %s", input_pdf_path)
    logger.info("Output directory: %s", output_dir)
    metadata.create(output_dir, sys.argv, Path.cwd(), input_pdf_path, args.page_range)
    _run_convert_pipeline(input_pdf_path, input_xml_path, output_dir, args)


def _check_bundle_path(path: Path) -> None:
    if not path.is_dir():
        logger.error("Bundle directory not found: %s", path)
        sys.exit(1)
    if path.suffix != ".s2l":
        logger.error("Bundle path must end in .s2l: %s", path)
        sys.exit(1)
    if not (path / metadata.METADATA_FILENAME).exists():
        logger.error("No metadata file found in bundle: %s", path)
        sys.exit(1)


def _update(args: argparse.Namespace) -> None:
    output_dir = args.bundle
    _check_bundle_path(output_dir)

    input_xml_path = args.xml
    if input_xml_path is not None:
        _validate_xml_path(input_xml_path)

    maybe_ignored_args = [f.name for f in fields(ConvertSettings) if getattr(args, f.name, UNSET) is not UNSET]
    if maybe_ignored_args:
        print()
        logger.warning(
            "Some of the used commandline args may be ignored if the stages that need them are already done: %r",
            maybe_ignored_args,
        )
        print()

    logger.info("Updating bundle: %s", output_dir)
    _run_convert_pipeline(None, input_xml_path, output_dir, args)


def _fix(args: argparse.Namespace) -> None:
    output_dir = args.bundle
    _check_bundle_path(output_dir)

    logger.info("Fixing LilyPond for bundle: %s", output_dir)
    _run_fix_pipeline(output_dir, args)


@contextmanager
def _error_handling(verbose: bool) -> Iterator[None]:
    # noinspection PyBroadException
    try:
        yield
    except PipelineError as e:
        log = logger.exception if verbose else logger.error
        log("%s", e)
        sys.exit(1)
    except Exception:
        logger.exception("Oops, something went wrong.")
        sys.exit(2)


def _run_convert_pipeline(
    input_pdf_path: Path | None,
    input_xml_path: Path | None,
    output_dir: Path,
    args: argparse.Namespace,
) -> None:
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

    with _error_handling(args.verbose):
        convert_pipeline.run(input_pdf_path, input_xml_path, output_dir, settings)


def _run_fix_pipeline(output_dir: Path, args: argparse.Namespace) -> None:
    settings_kwargs = {}
    for field in fields(FixSettings):
        name = field.name
        value = getattr(args, name, UNSET)

        if value is UNSET:
            continue

        settings_kwargs[name] = value
    settings = FixSettings(**settings_kwargs)

    with _error_handling(args.verbose):
        fix_pipeline.run(output_dir, settings)
