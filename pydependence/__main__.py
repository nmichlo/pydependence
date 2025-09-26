# SPDX-License-Identifier: MIT
# Copyright (c) 2024 Nathan Juraj Michlo

import argparse
import logging
import typing

from pydependence._cli import pydeps
from pydependence._core.requirements_map import NoConfiguredRequirementMappingError

LOGGER = logging.getLogger(__name__)

# ========================================================================= #
# CLI                                                                       #
# ========================================================================= #


if typing.TYPE_CHECKING:

    class PyDepsCliArgsProto(typing.Protocol):
        config: str
        dry_run: bool
        exit_zero: bool


def _parse_args() -> "PyDepsCliArgsProto":
    """
    Make argument parser for:
    `config`, required
    `--dry-run`, optional
    `--exit-zero`, optional # always return success exit code even if files changed

    Then parse the arguments and return them.
    """
    parser = argparse.ArgumentParser(
        description="PyDependence: A tool for scanning and resolving python dependencies across files."
    )
    parser.add_argument(
        "config",
        type=str,
        help="The python file to analyse for dependencies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the script without making any changes.",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always return a success exit code, even if files changed.",
    )
    return parser.parse_args()


def _cli():
    # args
    args = _parse_args()

    # run
    try:
        changed = pydeps(
            config_path=args.config,
            dry_run=args.dry_run,
        )
    except NoConfiguredRequirementMappingError as e:
        LOGGER.critical(
            f"[pydependence] no configured requirement mapping found, either specify all missing version mappings or disable strict mode:\n{e}"
        )
        exit(1)

    # check if files changed
    if changed:
        LOGGER.info("[pydependence] files changed.")
        if args.exit_zero:
            LOGGER.info(
                "[pydependence] exit-zero enabled, returning success exit code."
            )
            exit(0)
        else:
            exit(1)
    else:
        LOGGER.info("[pydependence] files unchanged.")
        exit(0)


if __name__ == "__main__":
    # set default log level to info
    logging.basicConfig(level=logging.INFO)
    # run cli
    _cli()


# ========================================================================= #
# END                                                                       #
# ========================================================================= #
