#!/usr/bin/env python3

import argparse
import logging
import sys

from gdc_client import download, upload, settings
from gdc_client.exceptions import ClientError
from gdc_client import log as logger
from gdc_client import auth
from gdc_client import version
from gdc_client.common.config import GDCClientConfigShared, GDCClientArgumentParser


DESCRIPTION = """
The Genomic Data Commons Command Line Client
"""


# TODO FIXME replace w/ updated email @ go live
SUPPORT_EMAIL = "support@nci-gdc.datacommons.io"

ERROR_MSG = " ".join(
    [
        "An unexpected error has occurred during normal operation of the client.",
        "Please report the following exception to GDC support <{support_email}>.",
    ]
).format(support_email=SUPPORT_EMAIL)


def log_version_header(log):
    log.debug("gdc-client - {version}".format(version=version.__version__))


def main() -> None:

    parser = GDCClientArgumentParser(
        description=DESCRIPTION,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=version.__version__,
    )

    conf_parser = argparse.ArgumentParser(add_help=False)
    conf_parser.add_argument("--config")

    conf_parser_args, remaining_args = conf_parser.parse_known_args()

    config_loader = GDCClientConfigShared(conf_parser_args.config)

    # Generate template parser for use by all sub-commands. This will
    # contain any shared, top-level arguments and flags that will be
    # needed by most, if not all, subcommands.
    template = GDCClientArgumentParser(
        add_help=False,
    )

    logger.parser.config(template)
    auth.parser.config(template)

    # Create and configure sub-command parsers.
    subparsers = parser.add_subparsers(
        title="commands",
        dest="command",
        help="for more information, specify -h after a command",
    )
    subparsers.required = True

    download_subparser = subparsers.add_parser(
        "download",
        parents=[template],
        help="download data from the GDC",
    )
    download.parser.config(download_subparser, config_loader.to_dict("download"))

    upload_subparser = subparsers.add_parser(
        "upload",
        parents=[template],
        help="upload data to the GDC",
    )
    upload.parser.config(upload_subparser, config_loader.to_dict("upload"))

    settings_subparser = subparsers.add_parser(
        "settings",
        help="display default settings",
    )
    settings.parser.config(settings_subparser, conf_parser_args.config)

    # Parse and run.
    args = parser.parse_args(remaining_args)

    logger.setup_logging(args)

    log = logging.getLogger("gdc-client")
    log_version_header(log)

    try:
        # go
        if args.func(args):
            sys.exit(2)
    except ClientError as err:
        log.error(err)
        sys.exit(1)
    except KeyboardInterrupt:
        log.warning("Process cancelled by user.")
        sys.exit(130)
    except Exception as err:
        log.error(ERROR_MSG)
        log.exception(err)
        log.error("Exiting")
        sys.exit(1)
    else:
        # will hit this branch even if downloads fail
        # and debug is turned off
        log.debug("gdc-client exited normally")


if __name__ == "__main__":
    main()
