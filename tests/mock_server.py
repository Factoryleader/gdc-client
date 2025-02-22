from flask import Flask, Response, jsonify, request
from conftest import uuids, make_tarfile

import json
import os
import time
import typing

app = Flask(__name__)


def generate_sleep_intervals(num_exceptions: int = 6) -> int:
    """Generator to return sleep times for the first num_exceptions"""
    count = 0
    while count < num_exceptions:
        yield 5
        count += 1
    while True:
        yield 0


generator = generate_sleep_intervals()


@app.route("/files/versions", methods=["POST"])
@app.route("/v0/files/versions", methods=["POST"])
def files_versions():
    args = request.json
    if not args:
        return jsonify({"message": "Send non-empty JSON body"}), 400
    if "ids" not in args:
        return (
            jsonify({"message": "Pass in object with ids as key and list as value"}),
            400,
        )

    ids = args["ids"]
    if not isinstance(ids, list):
        return jsonify({"message": "Pass in a list of uuids"}), 400

    result = []
    files = uuids.keys()
    for i in ids:
        if i not in files:
            return jsonify({"message": f"{i} not found in {files}"}), 404
        else:
            result.append({"id": i, "latest_id": i})

    return jsonify(result)


@app.route("/v0/files", methods=["POST"])
@app.route("/files", methods=["POST"])
@app.route("/legacy/files", methods=["POST"])
@app.route("/v0/legacy/files", methods=["POST"])
def files():
    result = {
        "data": {
            "hits": [],
            "pagination": {
                "count": 0,
                "sort": "",
                "from": 0,
                "page": 0,
                "total": 0,
                "pages": 0,
                "size": 0,
            },
        },
        "warnings": {},
    }

    """
    [{
        'access':      'access level',
        'md5sum':      'md5.,
        'file_size':   1,
        'id':          'id.,
        'file_id':     'id.
        'annotations': [{'annotation_id': 'id'}]
        'index_files': [{'file_id': 'id'}]
    }]
    """

    args = request.json
    if not args:
        return ""

    try:
        filters = args.get("filters")
        fields = args.get("fields")
        size = args.get("size")

        if not size.isdigit():
            return jsonify(result)

        field_uuids = json.loads(filters)["content"][0]["content"]["value"]

        for s in range(int(size)):
            if not uuids:
                continue

            uuid = field_uuids.pop()
            node = uuids.get(uuid)

            hit = {}

            if not node:
                continue

            if "file_id" in fields:
                hit["id"] = uuid

            if "access" in fields and node.get("access"):
                hit["access"] = node["access"]

            if "file_size" in fields and node.get("file_size"):
                hit["file_size"] = node["file_size"]

            if "md5sum" in fields and node.get("md5sum"):
                hit["md5sum"] = node["md5sum"]

            if "annotations" in fields and node.get("annotations"):
                hit["annotations"] = [{"annotation_id": a} for a in node["annotations"]]

            if "index_files" in fields and node.get("related_files"):
                hit["index_files"] = [{"file_id": r} for r in node["related_files"]]

            result["data"]["hits"].append(hit)

    except Exception as e:
        print(f"Error {e}")

    result["data"]["pagination"]["size"] = size
    return jsonify(result)


@app.route("/data", methods=["POST"])
@app.route("/v0/data", methods=["POST"])
@app.route("/legacy/data", methods=["POST"])
@app.route("/v0/legacy/data", methods=["POST"])
@app.route("/data/<ids>", methods=["GET"])
@app.route("/v0/data/<ids>", methods=["GET"])
@app.route("/legacy/data/<ids>", methods=["GET"])
@app.route("/v0/legacy/data/<ids>", methods=["GET"])
def download(ids=""):

    data = ""
    filename = "test_file.txt"
    headers = request.headers

    ids = ids.split(",")

    if request.content_type == "application/json":
        args = request.json
        ids = args.get("ids")

    for i in ids:
        if i not in uuids.keys():
            return (
                jsonify({"message": f"{i} not found in {uuids.keys()}"}),
                404,
            )

    # determine if this is a stream range data request
    if "Range" in headers:
        return handle_range_request(ids=ids, headers=headers, filename=filename)

    is_tarfile = request.args.get("tarfile") is not None
    is_compress = request.args.get("compress") is not None or len(ids) > 1
    md5sum = ""

    if is_tarfile:
        filename = "test_file.tar"
        write_mode = "w|"

    if is_compress:
        write_mode = "w|gz"
        filename = "test_file.tar.gz"

    if is_tarfile or is_compress:
        # make tarfile
        make_tarfile(ids, filename, write_mode=write_mode)

        # load tarfile into memory to be returned
        with open(filename, "rb") as f:
            data = f.read()

        # delete tarfile so it can be downloaded by client
        os.remove(filename)

    else:
        data = uuids[ids[0]]["contents"]
        md5sum = uuids[ids[0]]["md5sum"]

    resp = Response(data)
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    resp.headers["Content-Type"] = "application/octet-stream"
    resp.headers["Content-Length"] = len(data)
    if md5sum:
        resp.headers["Content-Md5"] = md5sum

    return resp


def handle_range_request(
    ids: typing.List[str], headers: dict, filename: str
) -> Response:
    interval = headers["Range"]
    interval = interval.split("=")
    interval = interval[1].split("-")
    start = int(interval[0])
    end = int(interval[1]) + 1

    sleep_time = next(generator)
    # Long sleep times purposefully set to cause ReadTimeout in client
    time.sleep(sleep_time)

    data = uuids[ids[0]]["contents"][start:end]
    resp = Response(data)
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    resp.headers["Content-Type"] = "application/octet-stream"
    resp.headers["Content-Length"] = len(data)

    return resp
