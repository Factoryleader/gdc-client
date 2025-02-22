# ***************************************************************************************
# Title: LabAdvComp/parcel
# Author: Joshua S. Miller
# Date: May 26, 2016
# Code version: 0.1.13
# Availability: https://github.com/LabAdvComp/parcel
# ***************************************************************************************

from contextlib import contextmanager
import hashlib
import logging
import mmap
import os
import requests
import stat
import sys

from progressbar import (
    Bar,
    ETA,
    FileTransferSpeed,
    Percentage,
    ProgressBar,
)

from gdc_client.exceptions import MD5ValidationError
from gdc_client.parcel.download_stream import DownloadStream
from gdc_client.parcel import utils

# Logging
log = logging.getLogger("utils")

# Silence warnings from requests
try:
    requests.packages.urllib3.disable_warnings()
except Exception as e:
    log.debug(f"Unable to silence requests warnings: {str(e)}")


def check_transfer_size(actual, expected):
    """Simple validation on any expected versus actual sizes.

    :param int actual: The size that was actually transferred
    :param int actual: The size that was expected to be transferred

    """

    return actual == expected


def get_file_transfer_pbar(
    file_id: str,
    maxval: int,
    start_val: int = 0,
    desc: str = "Downloading",
) -> ProgressBar:
    """Create and initialize a custom progressbar

    Args:
        file_id: file_id to include in the debug message
        maxval: maximum value for the progress bar
        start_val: initial value for the progress bar
        desc: additional debug message before the file_id

    Returns:
        ProgressBar: progress bar instance
    """
    log.debug(f"{desc} {file_id}:")

    pbar = ProgressBar(
        widgets=[
            Percentage(),
            " ",
            Bar(marker="#", left="[", right="]"),
            " ",
            ETA(),
            " ",
            FileTransferSpeed(),
            " ",
        ],
        max_value=maxval,
        initial_value=start_val,
        fd=sys.stdout,
    )
    pbar.start()
    return pbar


def get_percentage_pbar(maxval: int):
    """Create and initialize a simple percentage progressbar"""
    pbar = ProgressBar(
        widgets=[
            Percentage(),
            " ",
            Bar(marker="#", left="[", right="]"),
            " ",
        ],
        max_value=maxval,
    )
    pbar.start()
    return pbar


def print_opening_header(file_id):
    log.debug("")
    log.debug("v{}v".format("{s:{c}^{n}}".format(s=f" {file_id} ", n=50, c="-")))


def print_closing_header(file_id):
    log.debug("^{}^".format("{s:{c}^{n}}".format(s=f" {file_id} ", n=50, c="-")))


def write_offset(path, data, offset):
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(data)


def read_offset(path, offset, size):
    with open(path, "r+b") as f:
        f.seek(offset)
        data = f.read(size)
        return data


def set_file_length(path, length):
    if os.path.isfile(path) and os.path.getsize(path) == length:
        return
    with open(path, "wb") as f:
        f.seek(length - 1)
        f.write(b"\0")
        f.truncate()


def remove_partial_extension(path):
    try:
        if not path.endswith(".partial"):
            log.warning("No partial extension found")
            log.warning(f"Got {path}")
            return
        log.debug("renaming to {}".format(path.replace(".partial", "")))
        os.rename(path, path.replace(".partial", ""))
    except Exception as e:
        raise Exception(f"Unable to remove partial extension: {str(e)}")


def check_file_existence_and_size(path, size):
    return os.path.isfile(path) and os.path.getsize(path) == size


def get_file_type(path):
    try:
        mode = os.stat(path).st_mode
        if stat.S_ISDIR(mode):
            return "directory"
        elif stat.S_ISCHR(mode):
            return "character device"
        elif stat.S_ISBLK(mode):
            return "block device"
        elif stat.S_ISREG(mode):
            return "regular"
        elif stat.S_ISFIFO(mode):
            return "fifo"
        elif stat.S_ISLNK(mode):
            return "link"
        elif stat.S_ISSOCK(mode):
            return "socket"
        else:
            return "unknown"
    except Exception as e:
        raise RuntimeError(f"Unable to get file type: {str(e)}")


def calculate_segments(start, stop, block):
    """return a list of blocks in sizes no larger than `block`, the last
    block can be smaller.

    """
    return [(a, min(stop, a + block) - 1) for a in range(start, stop, block)]


def md5sum(block):
    m = utils.md5()
    m.update(block)
    return m.hexdigest()


def md5sum_whole_file(fname):
    hash_md5 = utils.md5()

    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)

    return hash_md5.hexdigest()


def validate_file_md5sum(stream: DownloadStream, file_path: str) -> None:
    """Function to validate md5sum for given file if prerequisite checks pass

    Args:
        stream: initialized DownloadStream object
        file_path: file to validate
    Raises:
        MD5ValidationError: if correct DownloadStream flags are not set or
                            md5sum does not have given md5sum
    """
    if not stream.check_file_md5sum:
        log.debug("checksum validation disabled")
        return

    log.debug("Validating checksum...")
    if not stream.is_regular_file:
        raise MD5ValidationError("Not a regular file")

    if not stream.md5sum:
        raise MD5ValidationError(
            "Cannot validate this file since the server did not provide an md5sum. Use the '--no-file-md5sum' option to ignore this error."
        )
    if md5sum_whole_file(file_path) != stream.md5sum:
        raise MD5ValidationError("File checksum is invalid")


@contextmanager
def mmap_open(path):
    try:
        with open(path, "r+b") as f:
            mm = mmap.mmap(f.fileno(), 0)
            yield mm
    except Exception as e:
        raise RuntimeError(f"Unable to get file type: {str(e)}")


def STRIP(comment):
    return " ".join(comment.split())


def md5():
    md5_kwargs = {} if sys.version_info < (3, 9) else {"usedforsecurity": False}
    return hashlib.md5(**md5_kwargs)
