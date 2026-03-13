import argparse
import logging
import sys
from importlib.metadata import version

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        prog="score2ly",
        description="Convert musical scores to LilyPond format.",
    )
    parser.add_argument("input", nargs="?", help="Input file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('score2ly')}")

    args = parser.parse_args()

    if args.input is None:
        parser.print_help()
        sys.exit(0)

    logger.info("Processing: %s", args.input)
