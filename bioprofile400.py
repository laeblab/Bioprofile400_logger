#!/usr/bin/env python3
# -*- coding: utf8 -*-
import argparse
import codecs
import collections
import datetime
import gzip
import logging
import subprocess
import sys
import time
import traceback

from pathlib import Path

import coloredlogs
import xlsxwriter

from astm_serial.client import AstmConn


_LOGGER_NAME = "astm_logger"
_LOGGER_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

HEADER_ROW = "H"
HEADER_ROW_TIME = 13

NAME_ROW = "O"
NAME_ROW_NAME_1 = 2
NAME_ROW_NAME_2 = 3
NAME_ROW_TYPE = 15

ERROR_ROW = "C"
ERROR_ROW_MESSAGE = 3

ASSAY_ROW = "R"
ASSAY_ROW_NAME = 2
ASSAY_ROW_VALUE = 3
ASSAY_ROW_UNITS = 4


# Status messages returned by bioprofiler
STATUS_MESSAGES = (
    b"NOT RDY!EOD\r\n",
    b"BUSY!EOD\r\n",
    b"READY!EOD\r\n",
)


class AstmReader:
    def __init__(self, device):
        self.astm = AstmConn(port=str(device), timeout=1)

    def __iter__(self):
        while True:
            yield (datetime.datetime.now(), self.astm.get_data())


class AstmPlayback:
    def __init__(self, filepath):
        self.handle = open(filepath, "rb")

        header = self.handle.read(2)

        self.handle.seek(0)
        if header == b"\x1f\x8b":
            self.handle = gzip.GzipFile(fileobj=self.handle)

    def __iter__(self):
        for line in self.handle:
            line = line.decode("utf-8")
            timestamp, data = line.rstrip("\r\n").split("\t")
            timestamp = datetime.datetime.fromisoformat(timestamp)

            yield timestamp, codecs.decode(data, "hex")


class OddResult:
    def __init__(self, value):
        self.value = value


class ErrorResult:
    def __init__(self, value):
        self.value = value


def try_float(value):
    try:
        return float(value)
    except ValueError:
        return value
    except TypeError:
        return value


def parse_timestamp(value: str) -> str:
    return "%s-%s-%s %s:%s:%s" % (
        value[0:4],
        value[4:6],
        value[6:8],
        value[8:10],
        value[10:12],
        value[12:14],
    )


def parse_message(message, group):
    def _is(row, kind):
        return row[0].endswith(kind)

    def _new(sample_id):
        return {
            "group": group,
            "id": str(sample_id),
            "name_1": None,
            "name_2": None,
            "type": None,
            "assays": collections.OrderedDict(),
            "errors": [],
            "timestamp": None,
        }

    samples = []
    sample_id = 0
    sample = _new(sample_id)
    for _, line in message:
        row = [
            field.strip().decode("utf-8", errors="replace")
            for field in line.split(b"|")
        ]

        if _is(row, HEADER_ROW):
            if sample["assays"] or sample["errors"]:
                samples.append(sample)

            sample_id += 1
            sample = _new(sample_id)
            sample["timestamp"] = parse_timestamp(row[HEADER_ROW_TIME])
        elif _is(row, NAME_ROW):
            sample["name_1"] = row[NAME_ROW_NAME_1]
            sample["name_2"] = row[NAME_ROW_NAME_2]
            sample["type"] = row[NAME_ROW_TYPE]
        elif _is(row, ERROR_ROW):
            sample["errors"].append(row[ERROR_ROW_MESSAGE])
        elif _is(row, ASSAY_ROW):
            assay = row[ASSAY_ROW_NAME].replace("^", "")

            sample["assays"][assay] = {
                "value": row[ASSAY_ROW_VALUE],
                "units": row[ASSAY_ROW_UNITS],
            }

    if sample["assays"] or sample["errors"]:
        samples.append(sample)

    return samples


def build_table(rows):
    assays = collections.OrderedDict()
    for row in rows:
        for key, values in row["assays"].items():
            units = values["units"]

            if assays.setdefault(key, units) != units:
                assays[key] = OddResult("???")

    header_1 = ["Filename", "#", "Type", "ID", "Cup", "Timestamp"]
    header_1.extend(key for key in assays)

    header_2 = [None, None, None, None, None, None]
    header_2.extend(value for (_, value) in assays.items())

    table = [header_1, header_2]
    for row in rows:
        output_row = [
            row["group"],
            row["id"],
            row["type"],
            row["name_1"],
            row["name_2"],
            row["timestamp"],
        ]

        questionable_assays = []
        for key in assays:
            value = row["assays"].get(key, {}).get("value", None)
            if value and value.startswith("?"):
                questionable_assays.append(key)
                value = OddResult(value[1:])

            if value == "****":
                value = ErrorResult(None)

            output_row.append(value)

        output_row.extend(ErrorResult(err) for err in row["errors"])
        if questionable_assays:
            output_row.append(
                OddResult("Odd results for %s" % (", ".join(questionable_assays)))
            )

        table.append(output_row)

    return table


def write_xlsx(filename: str, table):
    workbook = xlsxwriter.Workbook(filename)
    worksheet = workbook.add_worksheet()

    result_is_odd = workbook.add_format({"bg_color": "yellow"})
    result_is_err = workbook.add_format({"bg_color": "red"})

    for ridx, row in enumerate(table):
        for cidx, cell in enumerate(row):
            value = cell
            cell_format = None
            if isinstance(cell, OddResult):
                value, cell_format = cell.value, result_is_odd
            elif isinstance(cell, ErrorResult):
                value, cell_format = cell.value, result_is_err

            worksheet.write(ridx, cidx, try_float(value), cell_format)

    workbook.close()


def write_playback(filepath, timestamp, message):
    with filepath.open("wt", encoding="utf-8") as handle:
        for mtime, mdata in message:
            handle.write("%s\t%s\n" % (mtime.isoformat(), mdata.hex()))

        # Write end-of-message for playback
        for _ in range(3):
            handle.write("%s\t%s\n" % (timestamp.isoformat(), ""))

        handle.flush()


def popen(cmd, **kwargs):
    kwargs.setdefault("start_new_session", True)

    return (cmd, subprocess.Popen(cmd, **kwargs))


def setup_logging(args):
    coloredlogs.install(
        level=args.log_level,
        fmt=_LOGGER_FORMAT,
    )

    filelog = logging.FileHandler(args.log_file)
    filelog.setLevel(logging.DEBUG)
    filelog.setFormatter(logging.Formatter(_LOGGER_FORMAT))

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(filelog)

    return logger


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("width", 79)

        super().__init__(*args, **kwargs)


def parse_args(argv):
    parser = argparse.ArgumentParser(formatter_class=HelpFormatter)

    group = parser.add_argument_group("Instrument")
    group.add_argument(
        "--instrument-device",
        type=Path,
        default=Path("/dev/ttyUSB0"),
        help="Path to instrument device",
    )
    group.add_argument(
        "--instrument-sleep",
        type=float,
        default=1,
        help="Sleep time between attempts at getting data from instrument",
    )
    group.add_argument(
        "--instrument-playback",
        type=Path,
        help="Log containing instrument data; will be played back as if from a real "
        "instrument, but without any wait-time.",
    )

    group = parser.add_argument_group("IO")
    group.add_argument(
        "--cache",
        type=Path,
        default=Path("cache"),
        help="Location in which to store local results and intermediate files",
    )
    group.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Location in which to store store processed results",
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


def log_exception(logger, error, when=""):
    logger.error("Unhandled exception%s%s:", " " if when else "", when)
    for line in traceback.format_exc().splitlines():
        logger.error("%s", line)


def main_core(args, logger):
    args.cache.mkdir(parents=True, exist_ok=True)

    # Sync in case the output folder was inaccessible at any point during the last run.
    command = [
        "rsync",
        "-a",
        # Ignore existing files, even if they have been changed in `output`
        "--ignore-existing",
        # Include directories
        "--include",
        "*/",
        # Include XLSX files
        "--include",
        "*.xlsx",
        # Exclude everything else
        "--exclude",
        "*",
        f"{args.cache}/",
        f"{args.output}/",
    ]
    procs = [popen(command)]

    if args.instrument_playback is None:
        logger.info("Reading from instrument at %s", str(args.instrument_device))
        instrument = AstmReader(args.instrument_device)
        logger.info("Listening to instrument")
    else:
        logger.info("Playback of instrument data from %s", args.instrument_playback)
        instrument = AstmPlayback(args.instrument_playback)
        args.instrument_sleep = 0
        logger.info("Playback started")

    message = []
    blank_line_count = 0
    for timestamp, data in instrument:
        for (cmd, proc) in list(procs):
            if proc.poll() is not None:
                procs.remove((cmd, proc))

                if proc.wait():
                    logger.error("Cmd failed with rc %i: %s", proc.returncode, cmd)
                else:
                    logger.debug("Cmd completed succesfully: %s", cmd)

        # Status messages may occur at the end (and start?) of lines of data
        for msg in STATUS_MESSAGES:
            if msg in data:
                logger.debug("Received instrument status: %r", data)
                data = data.replace(msg, b"")

        if data:
            blank_line_count = 0
            if not message:
                logger.info("New message arriving")

            logger.debug("Received %r", data.rstrip())
            message.append((timestamp, data))
            continue

        blank_line_count += 1
        if blank_line_count < 3:
            continue

        if message:
            logger.info("Message finished after %i lines.", len(message))

            if len(message) > 3:
                cache = args.cache / timestamp.strftime("%Y-%m")
                cache.mkdir(parents=True, exist_ok=True)

                filepath = cache / timestamp.strftime("%Y-%m-%d_%H_%M_%S_%f.raw")
                logger.info("Writing message playback to %s", filepath)

                try:
                    write_playback(filepath, timestamp, message)
                except Exception as error:
                    log_exception(logger, error, "when saving raw data")

                filepath = cache / timestamp.strftime("%Y-%m-%d_%H_%M_%S_%f.xlsx")
                logger.info("Writing results to %s", filepath)

                try:
                    group = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
                    rows = parse_message(message, group)
                    table = build_table(rows)
                    write_xlsx(filepath, table)

                    destination = args.output / cache.name
                    logger.info("Copying results to %s", destination)
                    cmd = ["rsync", "-a", filepath, f"{destination}/"]
                    procs.append(popen(cmd))
                except Exception as error:
                    log_exception(logger, error, "when saving XLSX file")

            message = []

        time.sleep(args.instrument_sleep)

    logger.info("Waiting for %i commands to finish ..", len(procs))
    for idx, (cmd, proc) in enumerate(procs, start=1):
        if proc.wait():
            logger.error("Cmd %i failed with rc %i: %s", idx, proc.returncode, cmd)
        else:
            logger.info("Cmd %i completed succesfully: %s", idx, cmd)

    logger.info("Done!")

    return 0


def main(argv):
    args = parse_args(argv)
    logger = setup_logging(args)

    try:
        return main_core(args, logger)
    except KeyboardInterrupt as error:
        log_exception(logger, error)
        logger.error("Terminated by CTRL + C")
    except Exception as error:
        log_exception(logger, error)
        logger.error("Logger terminated due to unhandled exception")

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
