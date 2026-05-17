#!/usr/bin/env python3
"""Archived failed Beck full-page Gemini batch experiment.

Do not use this harness for production Beck processing. It is retained only so
the failed pilot can be audited. The experiment showed that full-page Gemini
JSON output was slow, token-heavy, brittle, and did not produce reliable enough
builder-consumable ledgers.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ocr_beck_fresh_pilot import bbox_str, output_paths, parse_hocr, word_xml_id


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI}}}"
XML_ID = f"{{{XML}}}id"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)

FRESH_DIR = Path("ocr/beck2020_fresh")
GEMINI_DIR = FRESH_DIR / "gemini"
DEFAULT_IMAGES_DIR = FRESH_DIR / "images"
DEFAULT_PROMPT = Path("prompts/beck_gemini_diplomatic_json.md")
DEFAULT_PILOT_PAGES = (
    11,
    20,
    21,
    33,
    38,
    40,
    43,
    45,
    54,
    58,
    80,
    95,
    279,
    351,
    353,
    402,
    434,
    502,
    504,
    508,
    624,
    650,
    709,
    710,
    711,
)
REQUIRED_KEYS = {
    "page_tei_fragment",
    "footnote_events",
    "cross_page_continuations",
    "name_annotations",
    "bibl_annotations",
    "text_corrections",
    "uncertainties",
}
FOOTNOTE_LINK_FIELDS = [
    "page",
    "ref_xml_id",
    "note_xml_id",
    "n",
    "marker_bbox",
    "note_bbox",
    "confidence",
    "method",
    "reviewer",
]
FOOTNOTE_BLOCK_FIELDS = [
    "page",
    "note_xml_id",
    "n",
    "note_bbox",
    "first_line",
    "last_line",
    "confidence",
    "method",
    "reviewer",
]
FOOTNOTE_TRANSCRIPTION_FIELDS = [
    "page",
    "note_xml_id",
    "n",
    "transcription",
    "confidence",
    "method",
    "reviewer",
    "evidence",
]
TEXT_CORRECTION_FIELDS = [
    "correction_id",
    "pdf_page",
    "image_path",
    "line_index",
    "word_ids",
    "bbox",
    "old_ocr",
    "corrected_surface",
    "certainty",
    "reviewer",
    "decision",
    "evidence",
    "applied_at",
]
ANNOTATION_FIELDS = [
    "annotation_id",
    "page",
    "kind",
    "word_ids",
    "bbox",
    "surface",
    "tei",
    "confidence",
    "decision",
    "evidence",
]


@dataclass(frozen=True)
class RequestMeta:
    page: int
    page_id: str
    request_id: str
    primary_image: str
    next_image: str
    previous_image: str


def image_path(images_dir: Path, page: int) -> Path:
    return images_dir / f"beck-{page:04d}.png"


def mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def parse_pages(value: str, *, default_pilot: bool = False) -> list[int]:
    if default_pilot and value == "pilot":
        return list(DEFAULT_PILOT_PAGES)
    pages: list[int] = []
    for part in re.split(r"[\s,]+", value.strip()):
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if end < start:
                raise ValueError(f"invalid descending page range {part}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def gcs_join(prefix: str, name: str) -> str:
    return prefix.rstrip("/") + "/" + name


def local_image_for_uri(uri: str, images_dir: Path, gcs_prefix: str) -> Path | None:
    prefix = gcs_prefix.rstrip("/") + "/"
    if not uri.startswith(prefix):
        return None
    return images_dir / uri[len(prefix) :]


def page_id_from_text(value: str) -> str:
    match = re.search(r"\bREQUEST_ID:\s*(beck-\d{4})\b", value)
    return match.group(1) if match else ""


def request_prompt(page: int, next_page: int | None, previous_page: int | None, base_prompt: str) -> str:
    context_lines = [
        f"REQUEST_ID: beck-{page:04d}",
        f"PRIMARY_PAGE: {page}",
        f"PRIMARY_PAGE_ID: beck-{page:04d}",
        "IMAGE_ORDER:",
        f"1. PRIMARY page {page}; transcribe and annotate this page only.",
    ]
    order = 2
    if next_page is not None:
        context_lines.append(
            f"{order}. NEXT_CONTEXT page {next_page}; use only for footnote continuation from page {page}."
        )
        order += 1
    if previous_page is not None:
        context_lines.append(
            f"{order}. PREVIOUS_CONTEXT page {previous_page}; use only to identify a note that began before page {page}."
        )
    return "\n".join(context_lines) + "\n\n" + base_prompt.strip()


def page_hocr_context(fresh_dir: Path, page: int, label: str) -> str:
    hocr_path = output_paths(fresh_dir, page)["hocr"]
    if not hocr_path.exists():
        return f"{label}_HOCR_WORDS: unavailable"
    hocr_page = parse_hocr(hocr_path, page)
    lines = [f"{label}_HOCR_WORDS:"]
    for line in hocr_page.lines:
        parts = []
        for word in line.words:
            bbox = bbox_str(word.bbox) if word.bbox else ""
            parts.append(f"{word_xml_id(word)}[{bbox}]={word.text}")
        if parts:
            lines.append(f"L{line.index:03d}: " + " ".join(parts))
    return "\n".join(lines)


def make_request_line(
    page: int,
    images_dir: Path,
    fresh_dir: Path,
    gcs_image_prefix: str,
    base_prompt: str,
    previous_context_pages: set[int],
    max_page: int,
    max_output_tokens: int,
    temperature: float,
    include_hocr_context: bool,
) -> tuple[dict[str, Any], RequestMeta]:
    primary = image_path(images_dir, page)
    if not primary.exists():
        raise FileNotFoundError(primary)
    next_page = page + 1 if page < max_page and image_path(images_dir, page + 1).exists() else None
    previous_page = page - 1 if page in previous_context_pages and page > 1 and image_path(images_dir, page - 1).exists() else None

    prompt_text = request_prompt(page, next_page, previous_page, base_prompt)
    if include_hocr_context:
        context_blocks = [page_hocr_context(fresh_dir, page, "PRIMARY")]
        if next_page is not None:
            context_blocks.append(page_hocr_context(fresh_dir, next_page, "NEXT_CONTEXT"))
        if previous_page is not None:
            context_blocks.append(page_hocr_context(fresh_dir, previous_page, "PREVIOUS_CONTEXT"))
        prompt_text += "\n\n" + "\n\n".join(context_blocks)
    parts: list[dict[str, Any]] = [{"text": prompt_text}]
    image_entries = [(page, primary)]
    if next_page is not None:
        image_entries.append((next_page, image_path(images_dir, next_page)))
    if previous_page is not None:
        image_entries.append((previous_page, image_path(images_dir, previous_page)))
    for _image_page, path in image_entries:
        parts.append({"fileData": {"fileUri": gcs_join(gcs_image_prefix, path.name), "mimeType": mime_type(path)}})

    request = {
        "request": {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "topP": 1,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
    }
    meta = RequestMeta(
        page=page,
        page_id=f"beck-{page:04d}",
        request_id=f"beck-{page:04d}",
        primary_image=gcs_join(gcs_image_prefix, primary.name),
        next_image=gcs_join(gcs_image_prefix, image_path(images_dir, next_page).name) if next_page else "",
        previous_image=gcs_join(gcs_image_prefix, image_path(images_dir, previous_page).name) if previous_page else "",
    )
    return request, meta


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            count += 1
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return count


def write_request_manifest(path: Path, rows: list[RequestMeta], model: str, gcs_prefix: str) -> None:
    payload = {
        "model": model,
        "gcs_image_prefix": gcs_prefix.rstrip("/") + "/",
        "request_count": len(rows),
        "requests": [row.__dict__ for row in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_requests(args: argparse.Namespace) -> int:
    images_dir = Path(args.images_dir)
    fresh_dir = Path(args.fresh_dir)
    pages = list(range(1, args.expected_pages + 1)) if args.pages == "all" else parse_pages(args.pages, default_pilot=True)
    previous_context_pages = set(parse_pages(args.previous_context_pages)) if args.previous_context_pages else set()
    base_prompt = Path(args.prompt).read_text(encoding="utf-8")
    requests: list[dict[str, Any]] = []
    metas: list[RequestMeta] = []
    for page in pages:
        request, meta = make_request_line(
            page,
            images_dir,
            fresh_dir,
            args.gcs_image_prefix,
            base_prompt,
            previous_context_pages,
            args.expected_pages,
            args.max_output_tokens,
            args.temperature,
            args.include_hocr_context,
        )
        requests.append(request)
        metas.append(meta)
    count = write_jsonl(Path(args.output), requests)
    write_request_manifest(Path(args.manifest), metas, args.model, args.gcs_image_prefix)
    print(f"Wrote {count} requests to {args.output}")
    print(f"Wrote request manifest to {args.manifest}")
    return 0


def iter_jsonl(paths: list[Path]) -> Iterable[tuple[Path, int, dict[str, Any]]]:
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                yield path, line_no, json.loads(line)


def request_parts(row: dict[str, Any]) -> list[dict[str, Any]]:
    contents = row.get("request", {}).get("contents", [])
    if not contents:
        return []
    return contents[0].get("parts", [])


def validate_requests(args: argparse.Namespace) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    images_dir = Path(args.images_dir)
    for path, line_no, row in iter_jsonl([Path(args.jsonl)]):
        parts = request_parts(row)
        if not parts:
            errors.append(f"{path}:{line_no}: missing request.contents[0].parts")
            continue
        text = parts[0].get("text", "")
        page_id = page_id_from_text(text)
        if not page_id:
            errors.append(f"{path}:{line_no}: missing REQUEST_ID beck-NNNN in prompt text")
        elif page_id in seen:
            errors.append(f"{path}:{line_no}: duplicate REQUEST_ID {page_id}")
        else:
            seen.add(page_id)
        file_parts = [part.get("fileData") or part.get("file_data") for part in parts[1:]]
        file_parts = [part for part in file_parts if part]
        if not file_parts:
            errors.append(f"{path}:{line_no}: request has no fileData image parts")
        for index, file_data in enumerate(file_parts, start=1):
            uri = file_data.get("fileUri") or file_data.get("file_uri") or ""
            if not uri.startswith("gs://"):
                errors.append(f"{path}:{line_no}: image part {index} is not a gs:// URI")
            if args.gcs_image_prefix:
                local = local_image_for_uri(uri, images_dir, args.gcs_image_prefix)
                if local is None:
                    warnings.append(f"{path}:{line_no}: image URI outside expected prefix: {uri}")
                elif not local.exists():
                    errors.append(f"{path}:{line_no}: local mirror missing for {uri}: {local}")
        if re.search(r"^\d+\.\s+NEXT_CONTEXT\b", text, flags=re.MULTILINE) and len(file_parts) < 2:
            errors.append(f"{path}:{line_no}: prompt declares NEXT_CONTEXT but only {len(file_parts)} image part(s)")
        if len(file_parts) > 3:
            errors.append(f"{path}:{line_no}: more than primary/next/previous image parts")
    if args.expected_count is not None and len(seen) != args.expected_count:
        errors.append(f"REQUEST_COUNT_MISMATCH: {len(seen)} requests vs expected {args.expected_count}")
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(seen)} Gemini batch requests")
    return 0


def extract_response_text(row: dict[str, Any]) -> str:
    candidates = row.get("response", {}).get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict))


def strip_json_fence(value: str) -> str:
    value = value.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json|JSON)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def load_model_json(text: str) -> dict[str, Any]:
    text = strip_json_fence(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_exc:
        parse_error = first_exc

    match = re.search(
        r'("page_tei_fragment"\s*:\s*")(?P<fragment>.*?)(?P<end>"\s*,\s*\n\s*"footnote_events"\s*:)',
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise parse_error
    repaired = (
        text[: match.start("fragment")]
        + json.dumps(match.group("fragment"), ensure_ascii=False)[1:-1]
        + text[match.start("end") :]
    )
    return json.loads(repaired)


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fragment = payload.get("page_tei_fragment")
    if isinstance(fragment, str) and ("\\n" in fragment or '\\"' in fragment):
        payload["page_tei_fragment"] = fragment.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
    return payload


def load_parsed_payload(path: Path) -> dict[str, Any]:
    return normalize_payload(json.loads(path.read_text(encoding="utf-8")))


def request_page_id(row: dict[str, Any]) -> str:
    for part in request_parts(row):
        text = part.get("text", "")
        if text:
            page_id = page_id_from_text(text)
            if page_id:
                return page_id
    return ""


def usage_row(page_id: str, row: dict[str, Any]) -> dict[str, str]:
    usage = row.get("response", {}).get("usageMetadata", {})
    return {
        "page_id": page_id,
        "prompt_token_count": str(usage.get("promptTokenCount", "")),
        "candidates_token_count": str(usage.get("candidatesTokenCount", "")),
        "total_token_count": str(usage.get("totalTokenCount", "")),
        "model_version": str(row.get("response", {}).get("modelVersion", "")),
        "finish_reason": str((row.get("response", {}).get("candidates") or [{}])[0].get("finishReason", "")),
        "status": str(row.get("status", "")),
    }


def parse_responses(args: argparse.Namespace) -> int:
    input_paths = [Path(value) for value in args.inputs]
    parsed_dir = Path(args.parsed_dir)
    raw_dir = Path(args.raw_text_dir)
    usage_rows: list[dict[str, str]] = []
    errors: list[str] = []
    parsed_count = 0
    parsed_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for path, line_no, row in iter_jsonl(input_paths):
        page_id = request_page_id(row) or f"line-{line_no:04d}"
        text = extract_response_text(row)
        (raw_dir / f"{page_id}.txt").write_text(text, encoding="utf-8")
        usage_rows.append(usage_row(page_id, row))
        if row.get("status"):
            errors.append(f"{path}:{line_no}: batch status {row.get('status')}")
            continue
        if not text.strip():
            errors.append(f"{path}:{line_no}: empty model response for {page_id}")
            continue
        try:
            payload = normalize_payload(load_model_json(text))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_no}: JSON parse failed for {page_id}: {exc}")
            continue
        payload.setdefault("page_id", page_id)
        (parsed_dir / f"{page_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        parsed_count += 1
    write_csv(Path(args.usage_csv), list(usage_rows[0].keys()) if usage_rows else [], usage_rows)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Parsed {parsed_count} response(s) with {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"Parsed {parsed_count} response(s)")
    print(f"Wrote usage CSV to {args.usage_csv}")
    return 0


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_fragment(value: str) -> ET.Element:
    fragment = value.strip()
    if not fragment:
        raise ET.ParseError("empty page_tei_fragment")
    try:
        return ET.fromstring(fragment)
    except ET.ParseError:
        wrapped = f'<wrapper xmlns="{TEI}">{fragment}</wrapper>'
        wrapper = ET.fromstring(wrapped)
        children = list(wrapper)
        if len(children) != 1:
            raise ET.ParseError(f"fragment produced {len(children)} top-level elements")
        return children[0]


def is_accepted(row: dict[str, Any]) -> bool:
    decision = str(row.get("decision") or row.get("status") or "").strip().casefold()
    if decision in {"accepted", "accept", "apply"}:
        return True
    if row.get("accepted") is True:
        return True
    return False


def has_exact_span(row: dict[str, Any]) -> bool:
    word_ids = row.get("word_ids") or row.get("word_id") or ""
    bbox = row.get("bbox") or row.get("marker_bbox") or row.get("note_bbox") or ""
    if isinstance(word_ids, list):
        word_ids = " ".join(str(item) for item in word_ids)
    if isinstance(bbox, list):
        bbox = " ".join(str(item) for item in bbox)
    return bool(str(word_ids).strip() or str(bbox).strip())


def validate_parsed(args: argparse.Namespace) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    count = 0
    for path in sorted(Path(args.parsed_dir).glob("*.json")):
        count += 1
        payload = load_parsed_payload(path)
        missing = sorted(REQUIRED_KEYS - set(payload))
        if missing:
            errors.append(f"{path}: missing required keys {', '.join(missing)}")
        page_id = str(payload.get("page_id") or path.stem)
        try:
            fragment = parse_fragment(str(payload.get("page_tei_fragment") or ""))
        except ET.ParseError as exc:
            errors.append(f"{path}: page_tei_fragment is not parseable XML: {exc}")
            fragment = None
        if fragment is not None and local_name(fragment.tag) != "div":
            warnings.append(f"{path}: page_tei_fragment top element is {local_name(fragment.tag)}, expected div")
        for key in ("footnote_events", "cross_page_continuations", "name_annotations", "bibl_annotations", "text_corrections"):
            rows = payload.get(key, [])
            if not isinstance(rows, list):
                errors.append(f"{path}: {key} must be a list")
                continue
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    errors.append(f"{path}: {key}[{index}] must be an object")
                    continue
                if is_accepted(row) and key in {"name_annotations", "bibl_annotations", "text_corrections"} and not has_exact_span(row):
                    errors.append(f"{path}: accepted {key}[{index}] has no exact word_ids or bbox span")
                if row.get("target") and str(row["target"]).startswith("#") and fragment is not None:
                    ids = {element.get(XML_ID) or element.get("xml:id") for element in fragment.iter()}
                    if str(row["target"])[1:] not in ids:
                        errors.append(f"{path}: {key}[{index}] target {row['target']} is absent from fragment")
        for index, row in enumerate(payload.get("cross_page_continuations", []) or [], start=1):
            status = str(row.get("status") or row.get("decision") or "").strip().casefold()
            if status not in {"continuing", "continued", "resolved", "uncertain", "accepted", "rejected"}:
                warnings.append(f"{path}: cross_page_continuations[{index}] has unrecognized status {status!r}")
            if not row.get("evidence"):
                errors.append(f"{path}: cross_page_continuations[{index}] lacks page-image evidence")
        if args.require_page_id_match and payload.get("page_id") and payload.get("page_id") != page_id:
            errors.append(f"{path}: page_id mismatch {payload.get('page_id')} vs {page_id}")
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Validated {count} parsed Gemini page response(s)")
    return 0


def tei_root() -> tuple[ET.Element, ET.Element]:
    root = ET.Element(NS + "TEI")
    root.set(XML_ID, "beck2020_fresh_gemini_native")
    header = ET.SubElement(root, NS + "teiHeader")
    file_desc = ET.SubElement(header, NS + "fileDesc")
    title_stmt = ET.SubElement(file_desc, NS + "titleStmt")
    ET.SubElement(title_stmt, NS + "title").text = "Beck 2020 Gemini-native diplomatic page fragments"
    pub_stmt = ET.SubElement(file_desc, NS + "publicationStmt")
    ET.SubElement(pub_stmt, NS + "p").text = "Private local Gemini batch comparison artifact; not a public edition."
    source_desc = ET.SubElement(file_desc, NS + "sourceDesc")
    ET.SubElement(source_desc, NS + "p").text = "Generated from Gemini structured JSON responses over local Beck page images."
    text = ET.SubElement(root, NS + "text")
    body = ET.SubElement(text, NS + "body")
    edition = ET.SubElement(body, NS + "div")
    edition.set("type", "edition")
    edition.set(XML_ID, "beck-gemini-native-edition")
    return root, edition


def stitch_fragments(args: argparse.Namespace) -> int:
    root, edition = tei_root()
    count = 0
    for path in sorted(Path(args.parsed_dir).glob("beck-*.json")):
        payload = load_parsed_payload(path)
        fragment = parse_fragment(str(payload.get("page_tei_fragment") or ""))
        page_id = str(payload.get("page_id") or path.stem)
        if not (fragment.get(XML_ID) or fragment.get("xml:id")):
            fragment.set(XML_ID, f"{page_id}-gemini-page")
        fragment.set("source", path.as_posix())
        edition.append(fragment)
        count += 1
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {count} stitched Gemini page fragment(s) to {output}")
    return 0


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{key: value for key, value in row.items() if key is not None} for row in csv.DictReader(handle)]


def csv_value(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value)
    return ""


def page_number(payload: dict[str, Any], fallback_stem: str) -> str:
    value = str(payload.get("page") or payload.get("primary_page") or "").strip()
    if value.isdigit():
        return value
    match = re.search(r"(\d{4})", str(payload.get("page_id") or fallback_stem))
    return str(int(match.group(1))) if match else ""


def page_as_int(page: str) -> int:
    return int(page) if str(page).isdigit() else 0


def image_path_text(page: str) -> str:
    page_i = page_as_int(page)
    return f"ocr/beck2020_fresh/images/beck-{page_i:04d}.png" if page_i else ""


def export_ledgers(args: argparse.Namespace) -> int:
    outdir = Path(args.output_dir)
    existing_footnote_refs: set[str] = set()
    existing_page_notes: set[tuple[str, str]] = set()
    for row in read_csv_dicts(FRESH_DIR / "review" / "accepted_footnote_links.csv"):
        if row.get("ref_xml_id"):
            existing_footnote_refs.add(row["ref_xml_id"])
        page = str(row.get("page") or "").strip()
        n = str(row.get("n") or "").strip()
        if page and n:
            existing_page_notes.add((page, n))
    footnote_links: list[dict[str, str]] = []
    footnote_blocks: list[dict[str, str]] = []
    footnote_transcriptions: list[dict[str, str]] = []
    text_corrections: list[dict[str, str]] = []
    name_annotations: list[dict[str, str]] = []
    bibl_annotations: list[dict[str, str]] = []
    for path in sorted(Path(args.parsed_dir).glob("*.json")):
        payload = load_parsed_payload(path)
        page = page_number(payload, path.stem)
        page_i = page_as_int(page)
        for index, event in enumerate(payload.get("footnote_events", []) or [], start=1):
            if not isinstance(event, dict) or not is_accepted(event):
                continue
            marker_bbox = csv_value(event, "marker_bbox", "ref_bbox")
            note_bbox = csv_value(event, "note_bbox")
            anchor_word_id = csv_value(event, "word_id", "word_ids", "anchor_word_id", "anchor_word_ids")
            if not (marker_bbox and note_bbox):
                continue
            if "beck-fresh-p" not in anchor_word_id:
                continue
            note_id = csv_value(event, "note_xml_id", "note_id") or (
                f"beck-fresh-gemini-fn-p{page_i:04d}-{index:03d}" if page_i else f"beck-fresh-gemini-fn-{path.stem}-{index:03d}"
            )
            ref_id = csv_value(event, "ref_xml_id", "ref_id")
            if not ref_id.startswith("beck-fresh-ref-"):
                continue
            n = csv_value(event, "n", "label")
            if ref_id in existing_footnote_refs or (page, n) in existing_page_notes:
                continue
            method = csv_value(event, "method") or "gemini-2.5-pro-batch"
            reviewer = csv_value(event, "reviewer") or "gemini-ledger"
            if ref_id:
                footnote_links.append(
                    {
                        "page": page,
                        "ref_xml_id": ref_id,
                        "note_xml_id": note_id,
                        "n": n,
                        "marker_bbox": marker_bbox,
                        "note_bbox": note_bbox,
                        "confidence": csv_value(event, "confidence"),
                        "method": method,
                        "reviewer": reviewer,
                    }
                )
            if note_bbox:
                footnote_blocks.append(
                    {
                        "page": page,
                        "note_xml_id": note_id,
                        "n": n,
                        "note_bbox": note_bbox,
                        "first_line": csv_value(event, "first_line"),
                        "last_line": csv_value(event, "last_line"),
                        "confidence": csv_value(event, "confidence"),
                        "method": method,
                        "reviewer": reviewer,
                    }
                )
            transcription = csv_value(event, "transcription", "note_text", "text")
            if transcription:
                footnote_transcriptions.append(
                    {
                        "page": page,
                        "note_xml_id": note_id,
                        "n": n,
                        "transcription": transcription,
                        "confidence": csv_value(event, "confidence"),
                        "method": method,
                        "reviewer": reviewer,
                        "evidence": csv_value(event, "evidence"),
                    }
                )
        for index, row in enumerate(payload.get("text_corrections", []) or [], start=1):
            if not isinstance(row, dict) or not is_accepted(row):
                continue
            if not has_exact_span(row):
                continue
            corrected_surface = csv_value(row, "corrected_surface", "surface")
            decision = csv_value(row, "decision") or "accepted"
            if not corrected_surface and decision.strip().casefold() not in {"delete", "omit"}:
                continue
            text_corrections.append(
                {
                    "correction_id": csv_value(row, "correction_id")
                    or (f"beck-gemini-p{page_i:04d}-{index:03d}" if page_i else f"beck-gemini-{path.stem}-{index:03d}"),
                    "pdf_page": page,
                    "image_path": csv_value(row, "image_path") or image_path_text(page),
                    "line_index": csv_value(row, "line_index"),
                    "word_ids": csv_value(row, "word_ids", "word_id"),
                    "bbox": csv_value(row, "bbox"),
                    "old_ocr": csv_value(row, "old_ocr", "old_surface"),
                    "corrected_surface": corrected_surface,
                    "certainty": csv_value(row, "certainty", "confidence"),
                    "reviewer": csv_value(row, "reviewer") or "gemini-ledger",
                    "decision": decision,
                    "evidence": csv_value(row, "evidence"),
                    "applied_at": csv_value(row, "applied_at"),
                }
            )
        for key, target in (("name_annotations", name_annotations), ("bibl_annotations", bibl_annotations)):
            for index, row in enumerate(payload.get(key, []) or [], start=1):
                if not isinstance(row, dict) or not is_accepted(row):
                    continue
                if not has_exact_span(row):
                    continue
                target.append(
                    {
                        "annotation_id": csv_value(row, "annotation_id")
                        or (
                            f"beck-gemini-{key[:-1]}-p{page_i:04d}-{index:03d}"
                            if page_i
                            else f"beck-gemini-{key[:-1]}-{path.stem}-{index:03d}"
                        ),
                        "page": page,
                        "kind": csv_value(row, "kind", "type") or ("bibl" if key == "bibl_annotations" else "name"),
                        "word_ids": csv_value(row, "word_ids", "word_id"),
                        "bbox": csv_value(row, "bbox"),
                        "surface": csv_value(row, "surface", "text"),
                        "tei": csv_value(row, "tei"),
                        "confidence": csv_value(row, "confidence"),
                        "decision": csv_value(row, "decision") or "accepted",
                        "evidence": csv_value(row, "evidence"),
                    }
                )
    write_csv(outdir / "accepted_footnote_links.csv", FOOTNOTE_LINK_FIELDS, footnote_links)
    write_csv(outdir / "accepted_footnote_blocks.csv", FOOTNOTE_BLOCK_FIELDS, footnote_blocks)
    write_csv(outdir / "accepted_footnote_transcriptions.csv", FOOTNOTE_TRANSCRIPTION_FIELDS, footnote_transcriptions)
    write_csv(outdir / "text_corrections.csv", TEXT_CORRECTION_FIELDS, text_corrections)
    write_csv(outdir / "name_annotations.csv", ANNOTATION_FIELDS, name_annotations)
    write_csv(outdir / "bibl_annotations.csv", ANNOTATION_FIELDS, bibl_annotations)
    print(f"Wrote Gemini accepted ledgers to {outdir}")
    return 0


def write_summary(args: argparse.Namespace) -> int:
    parsed_dir = Path(args.parsed_dir)
    parsed_paths = sorted(parsed_dir.glob("*.json"))
    counts = {key: 0 for key in REQUIRED_KEYS if key != "page_tei_fragment"}
    accepted_counts = {
        "accepted_footnote_events": 0,
        "accepted_name_annotations": 0,
        "accepted_bibl_annotations": 0,
        "accepted_text_corrections": 0,
    }
    pages_with_uncertainties: list[str] = []
    for path in parsed_paths:
        payload = load_parsed_payload(path)
        for key in counts:
            rows = payload.get(key, [])
            if isinstance(rows, list):
                counts[key] += len(rows)
        if payload.get("uncertainties"):
            pages_with_uncertainties.append(path.stem)
        accepted_counts["accepted_footnote_events"] += sum(
            1 for row in payload.get("footnote_events", []) or [] if isinstance(row, dict) and is_accepted(row)
        )
        accepted_counts["accepted_name_annotations"] += sum(
            1 for row in payload.get("name_annotations", []) or [] if isinstance(row, dict) and is_accepted(row)
        )
        accepted_counts["accepted_bibl_annotations"] += sum(
            1 for row in payload.get("bibl_annotations", []) or [] if isinstance(row, dict) and is_accepted(row)
        )
        accepted_counts["accepted_text_corrections"] += sum(
            1 for row in payload.get("text_corrections", []) or [] if isinstance(row, dict) and is_accepted(row)
        )
    lines = [
        "# Beck Gemini Batch Summary",
        "",
        f"- Parsed pages: {len(parsed_paths)}",
        *[f"- {key}: {value}" for key, value in sorted(counts.items())],
        *[f"- {key}: {value}" for key, value in sorted(accepted_counts.items())],
        f"- Pages with uncertainties: {len(pages_with_uncertainties)}",
    ]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote summary to {output}")
    return 0


def write_job_request(args: argparse.Namespace) -> int:
    model = args.model
    if not model.startswith("publishers/") and not model.startswith("projects/"):
        model = f"publishers/google/models/{model}"
    payload = {
        "displayName": args.display_name,
        "model": model,
        "inputConfig": {
            "instancesFormat": "jsonl",
            "gcsSource": {"uris": [args.input_uri]},
        },
        "outputConfig": {
            "predictionsFormat": "jsonl",
            "gcsDestination": {"outputUriPrefix": args.output_uri},
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Vertex AI batchPredictionJobs request body to {output}")
    return 0


def add_common_request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--images-dir", default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--gcs-image-prefix", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_p = subparsers.add_parser("build-requests", help="Build Vertex AI Gemini batch JSONL requests")
    add_common_request_args(build_p)
    build_p.add_argument("--fresh-dir", default=FRESH_DIR)
    build_p.add_argument("--pages", default="pilot", help="'pilot', 'all', comma list, or ranges such as 20-25")
    build_p.add_argument("--previous-context-pages", default="")
    build_p.add_argument("--expected-pages", type=int, default=711)
    build_p.add_argument("--prompt", default=DEFAULT_PROMPT)
    build_p.add_argument("--model", default="gemini-2.5-pro")
    build_p.add_argument("--max-output-tokens", type=int, default=32768)
    build_p.add_argument("--temperature", type=float, default=0)
    build_p.add_argument("--include-hocr-context", action="store_true")
    build_p.add_argument("--output", default=GEMINI_DIR / "requests" / "pilot_requests.jsonl")
    build_p.add_argument("--manifest", default=GEMINI_DIR / "requests" / "pilot_request_manifest.json")
    build_p.set_defaults(func=build_requests)

    validate_p = subparsers.add_parser("validate-requests", help="Validate local Gemini batch request JSONL")
    add_common_request_args(validate_p)
    validate_p.add_argument("jsonl")
    validate_p.add_argument("--expected-count", type=int)
    validate_p.set_defaults(func=validate_requests)

    parse_p = subparsers.add_parser("parse-responses", help="Parse Vertex AI output JSONL into per-page JSON")
    parse_p.add_argument("inputs", nargs="+")
    parse_p.add_argument("--parsed-dir", default=GEMINI_DIR / "parsed_responses")
    parse_p.add_argument("--raw-text-dir", default=GEMINI_DIR / "raw_response_text")
    parse_p.add_argument("--usage-csv", default=GEMINI_DIR / "usage" / "usage.csv")
    parse_p.set_defaults(func=parse_responses)

    validate_parsed_p = subparsers.add_parser("validate-parsed", help="Validate parsed Gemini JSON schema and fragments")
    validate_parsed_p.add_argument("--parsed-dir", default=GEMINI_DIR / "parsed_responses")
    validate_parsed_p.add_argument("--require-page-id-match", action="store_true")
    validate_parsed_p.set_defaults(func=validate_parsed)

    stitch_p = subparsers.add_parser("stitch-fragments", help="Stitch Gemini-native TEI page fragments")
    stitch_p.add_argument("--parsed-dir", default=GEMINI_DIR / "parsed_responses")
    stitch_p.add_argument("--output", default=GEMINI_DIR / "outputs" / "beck2020_gemini_native_pages.xml")
    stitch_p.set_defaults(func=stitch_fragments)

    export_p = subparsers.add_parser("export-ledgers", help="Export accepted Gemini annotations to builder ledgers")
    export_p.add_argument("--parsed-dir", default=GEMINI_DIR / "parsed_responses")
    export_p.add_argument("--output-dir", default=GEMINI_DIR / "accepted_ledgers")
    export_p.set_defaults(func=export_ledgers)

    summary_p = subparsers.add_parser("summary", help="Write a compact parsed-response summary")
    summary_p.add_argument("--parsed-dir", default=GEMINI_DIR / "parsed_responses")
    summary_p.add_argument("--output", default=GEMINI_DIR / "summaries" / "pilot_summary.md")
    summary_p.set_defaults(func=write_summary)

    job_p = subparsers.add_parser("write-job-request", help="Write a REST request body for Vertex AI batch submission")
    job_p.add_argument("--input-uri", required=True, help="GCS URI of the JSONL request file")
    job_p.add_argument("--output-uri", required=True, help="GCS output prefix for predictions")
    job_p.add_argument("--model", default="gemini-2.5-pro")
    job_p.add_argument("--display-name", default="beck2020-fresh-gemini-batch")
    job_p.add_argument("--output", default=GEMINI_DIR / "requests" / "batch_prediction_job_request.json")
    job_p.set_defaults(func=write_job_request)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
