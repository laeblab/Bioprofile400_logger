#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import datetime
import sys

from pathlib import Path

from bioprofile400 import (
    AstmPlayback,
    HelpFormatter,
    build_table,
    parse_message,
    setup_logging,
    write_xlsx,
)

DEFAULT_OUTPUT_FILE = "bioprofile_%Y-%m-%d_%H_%M_%S_%f.xlsx"


def read_playback(filepath):
    reader = AstmPlayback(filepath)
    message = list(reader)

    return parse_message(message, filepath.name.split(".", 1)[0])


def read_playbacks(log, filepaths):
    rows = []
    for filepath in sorted(filepaths):
        if filepath.suffix.lower() != ".raw":
            log.warning("File is not a .raw file, skipping: %s", filepath)
            continue

        log.info("Reading playback: %s", filepath)
        rows.extend(read_playback(filepath))

    return rows


def parse_args(argv):
    parser = argparse.ArgumentParser(formatter_class=HelpFormatter)

    parser.add_argument(
        "raw_files",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="One ore more .raw files to be converted to XLSX.",
    )

    parser.add_argument(
        "--output-file",
        type=Path,
        metavar="FILE",
        default=Path(datetime.datetime.now().strftime(DEFAULT_OUTPUT_FILE)),
        help="Results from the raw files are written to this file as XLSX file.",
    )

    group = parser.add_argument_group("Logging")
    group.add_argument(
        "--log-file",
        type=Path,
        default=Path("bioprofile400.log"),
        help="Location in which to store store processed results",
    )
    group.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Verbosity of printed log messages",
    )

    return parser.parse_args(argv)


def main(argv) -> int:
    args = parse_args(argv)
    log = setup_logging(args)

    log.info("Reading playbacks ..")
    rows = read_playbacks(log, args.raw_files)
    table = build_table(rows)

    log.info("Writing XLSX to %s", args.output_file)
    write_xlsx(args.output_file, table)

    log.info("Done!")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
