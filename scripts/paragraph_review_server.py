#!/usr/bin/env python3
"""Serve the local viewer and persist paragraph review decisions."""
from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile


REPO_ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = (
    REPO_ROOT
    / "corpus"
    / "dioscorides"
    / "editions"
    / "tlg0656.tlg001.sprengel1830-comm"
    / "paragraph_review_decisions.json"
)
API_PATH = "/api/paragraph-review"
DEFAULT_DECISIONS = {
    "schema": "tei-maker.paragraph-review.v1",
    "edition": "tlg0656.tlg001.sprengel1830-comm",
    "pages": {},
}


def load_decisions() -> dict[str, object]:
    if not DECISIONS_PATH.exists():
        return dict(DEFAULT_DECISIONS)
    with DECISIONS_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("pages"), dict):
        raise ValueError(f"Invalid paragraph decisions JSON: {DECISIONS_PATH}")
    return data


def write_decisions(data: dict[str, object]) -> dict[str, object]:
    if not isinstance(data, dict) or not isinstance(data.get("pages"), dict):
        raise ValueError("Request body must be a JSON object with a pages object")
    data.setdefault("schema", DEFAULT_DECISIONS["schema"])
    data.setdefault("edition", DEFAULT_DECISIONS["edition"])
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=DECISIONS_PATH.parent,
        prefix=f".{DECISIONS_PATH.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_name = handle.name
    Path(temp_name).replace(DECISIONS_PATH)
    return data


class ParagraphReviewHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == API_PATH:
            try:
                self.send_json(HTTPStatus.OK, load_decisions())
            except Exception as error:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
            return
        super().do_GET()

    def do_PUT(self) -> None:
        self.handle_write()

    def do_POST(self) -> None:
        self.handle_write()

    def handle_write(self) -> None:
        if self.path.split("?", 1)[0] != API_PATH:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            self.send_json(HTTPStatus.OK, write_decisions(payload))
        except Exception as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), ParagraphReviewHandler)
    url = f"http://{args.host}:{args.port}/viewer/?review=paragraphs#edition=sprengel1830-comm&page=341"
    print(f"Serving paragraph review viewer at {url}")
    print(f"Writing decisions to {DECISIONS_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
