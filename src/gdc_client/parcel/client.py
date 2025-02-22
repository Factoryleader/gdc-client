# ***************************************************************************************
# Title: LabAdvComp/parcel
# Author: Joshua S. Miller
# Date: May 26, 2016
# Code version: 0.1.13
# Availability: https://github.com/LabAdvComp/parcel
# ***************************************************************************************

from gdc_client.parcel import const
from gdc_client.parcel import utils
from gdc_client.parcel.download_stream import DownloadStream
from gdc_client.parcel.portability import Process
from gdc_client.parcel.segment import SegmentProducer

import logging
import os
import requests
import tempfile
import time

# Logging
log = logging.getLogger("client")


class Client:
    def __init__(
        self, url, token, n_procs, directory=None, verify=True, debug=False, **kwargs
    ):
        """Creates a parcel client object.

        :param str token:
            The authentication token that will be added to the HTTP
            X-Auth-Token header
        :param int n_procs:
            The number of processes to use in download
        :param str directory:
            The directory to which any data will be downloaded

        """

        DownloadStream.http_chunk_size = kwargs.get(
            "http_chunk_size", const.HTTP_CHUNK_SIZE
        )
        DownloadStream.check_segment_md5sums = kwargs.get("segment_md5sums", True)
        DownloadStream.check_file_md5sum = kwargs.get("file_md5sum", True)
        SegmentProducer.save_interval = kwargs.get("save_interval", const.SAVE_INTERVAL)

        self.debug = debug
        self.directory = directory or os.path.abspath(os.getcwd())
        self.directory = os.path.expanduser(self.directory)
        self.n_procs = n_procs
        self.start = None
        self.stop = None
        self.token = token
        self.verify = verify

    @staticmethod
    def fix_uri(url):
        """Fix an improperly formatted url that is missing a scheme

        :params str url: The url to be fixed
        :returns: Fixed url starting with a valid scheme

        """
        if not (url.startswith("https://") or url.startswith("http://")):
            url = f"https://{url}"
        return url

    @staticmethod
    def raise_for_write_permissions(directory):
        try:
            tempfile.NamedTemporaryFile(dir=directory).close()
        except OSError as e:
            raise OSError(
                utils.STRIP(
                    """Unable to write
            to download to directory '{directory}': {err}.  This
            error likely occurred because the program was launched
            from (or specified to download to) a protected
            directory.  If you are running this executable from an
            archive (*.zip, *.tar.gz, etc.) then extracting it
            from the archive might solve this problem. Otherwise,
            please see documentation on how to change/specify
            directory."""
                ).format(err=str(e), directory=directory)
            )

    def start_timer(self):
        """Start a download timer.

        :returns: None

        """

        self.start_time = time.time()

    def stop_timer(self, file_size=None):
        """Stop a download timer and pring a summary.

        :returns: None

        """

        self.stop_time = time.time()
        rate_info = ""
        if file_size and file_size > 0:
            rate = (int(file_size) * 8 / 1e9) / (self.stop_time - self.start_time)
            rate_info = f": {rate:.2f} Gbps average"

        log.debug("Download complete" + rate_info)

    def download_files(self, urls, *args, **kwargs):
        """Download a list of files.

        :params list file_ids:
            A list of strings containing the ids of the entities to download

        """

        # Short circuit if no urls given
        if not urls:
            log.warning("No file urls given.")
            return

        self.raise_for_write_permissions(self.directory)

        # Log file ids
        for url in urls:
            log.debug(f"Given url: {url}")

        # Download each file
        downloaded, errors = [], {}
        for url in urls:
            url = self.fix_uri(url)

            # Construct download stream
            stream = DownloadStream(url, self.directory, self.token)

            # Download file
            try:
                # validate temporary file before renaming to permanent file location
                self.parallel_download(stream)
                utils.validate_file_md5sum(
                    stream,
                    (
                        stream.temp_path
                        if os.path.isfile(stream.temp_path)
                        else stream.path
                    ),
                )
                if os.path.isfile(stream.temp_path):
                    utils.remove_partial_extension(stream.temp_path)
                downloaded.append(url)

            # Handle file download error, store error to print out later
            except Exception as e:
                errors[url] = str(e)
                if self.debug:
                    log.exception(e)
                    raise

            finally:
                utils.print_closing_header(url)

        # Print error messages
        for url, error in errors.items():
            file_id = url.split("/")[-1]
            log.error(f"{file_id}: {error}")

        return downloaded, errors

    def serial_download(self, stream):
        """Download file to directory serially."""
        self._download(1, stream)

    def parallel_download(self, stream):
        """Download file to directory in parallel."""
        self._download(self.n_procs, stream)

    def _download(self, nprocs, stream):
        """Start ``self.n_procs`` to download the file.

        :params str file_id:
            String containing the id of the entity to download

        """

        # Start stream
        utils.print_opening_header(stream.url)
        log.debug("Getting file information...")
        stream.init()

        # if there's no size/Content-Length in the http header
        # then you can't parallel stream it in chunks
        if not stream.size:
            # Do a regular TCP download in python
            return self._standard_tcp_download(stream)

        # Create segments producer to stream
        n_procs = 1 if stream.size < 0.01 * const.GB else nprocs
        producer = SegmentProducer(stream, n_procs)

        if producer.done:
            return

        def download_worker():
            while True:
                try:
                    segment = producer.q_work.get()
                    if segment is None:
                        log.debug("Producer returned with no more work")
                        return
                    stream.write_segment(segment, producer.q_complete)
                    # write_segment completed successfully, send sentinel value
                    # to master process to indicate a task was completed
                    producer.q_complete.put(None)
                except Exception as e:
                    # send sentinel value to master process even though
                    # write_segment failed to indicate a task is "finished"
                    producer.q_complete.put(None)
                    if self.debug:
                        raise
                    else:
                        log.error(f"Download aborted: {str(e)}")
                        # worker needs to stay alive until final sentinel value
                        # from master process is received
                        continue

        # Divide work amongst process pool
        pool = [Process(target=download_worker) for i in range(n_procs)]

        # Start pool
        for p in pool:
            p.start()

        self.start_timer()

        # Wait for file to finish download
        producer.wait_for_completion()
        self.stop_timer(stream.size)

    def _standard_tcp_download(self, stream):
        """Backup download method for when you can't
        stream data from the a source because the
        http headers did not contain a Content-Length

        """

        try:
            r = requests.get(stream.url, stream=True, verify=self.verify)

            if r.status_code == 200:
                stream.setup_directories()
                with open(stream.path, "wb") as f:
                    for chunk in r:
                        f.write(chunk)

            else:
                raise Exception(
                    f"[{r.status_code}] Unable to download url {stream.url}"
                )

            r.close()

        except Exception as e:
            log.error(e)
            raise Exception(f"Unable to connect to {stream.url}")
