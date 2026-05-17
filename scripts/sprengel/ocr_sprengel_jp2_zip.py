#!/usr/bin/env python3
"""Iterative hOCR/OCR runner for Sprengel Internet Archive JP2 zip files."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


DEFAULT_ZIP = Path("b23982500_0002_jp2.zip")
DEFAULT_OUTPUT = Path("ocr/sprengel/b23982500_0002")
DEFAULT_LANGS = ["lat", "grc", "ara", "heb", "syr"]
SCRIPT_PROFILES = [
    ("latin_greek", ["lat", "grc"]),
    ("arabic", ["ara"]),
    ("hebrew", ["heb"]),
    ("syriac", ["syr"]),
    ("script_latin", ["Latin"]),
    ("script_greek", ["Greek"]),
    ("script_arabic", ["Arabic"]),
    ("script_hebrew", ["Hebrew"]),
    ("script_syriac", ["Syriac"]),
]
WORD_CONF_RE = re.compile(r"x_wconf\s+(-?\d+(?:\.\d+)?)")
BBOX_RE = re.compile(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")
LATIN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z.\-]{3,}\b")
PAGE_REF_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3})?\b")


@dataclass
class OcrResult:
    hocr: str
    text: str
    avg_conf: float | None
    word_count: int


@dataclass
class WeakRegion:
    index: int
    bbox: tuple[int, int, int, int]
    avg_conf: float
    word_count: int
    text: str


def run_command(cmd: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def require_command(name: str) -> None:
    if not shutil.which(name):
        raise SystemExit(f"Missing required command: {name}")


def installed_tesseract_langs() -> set[str]:
    result = run_command(["tesseract", "--list-langs"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Could not list Tesseract languages")
    langs = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("List of available"):
            langs.add(line)
    return langs


def select_langs(required: list[str], allow_missing: bool) -> tuple[list[str], list[str]]:
    installed = installed_tesseract_langs()
    missing = [lang for lang in required if lang not in installed]
    if missing and not allow_missing:
        packages = " ".join(
            [
                "tesseract-ocr-lat",
                "tesseract-ocr-ara",
                "tesseract-ocr-heb",
                "tesseract-ocr-syr",
                "tesseract-ocr-script-latn",
                "tesseract-ocr-script-grek",
                "tesseract-ocr-script-arab",
                "tesseract-ocr-script-hebr",
                "tesseract-ocr-script-syrc",
            ]
        )
        raise SystemExit(
            "Missing Tesseract language data: "
            + ", ".join(missing)
            + "\nInstall with: sudo apt install "
            + packages
            + "\nFor a non-final smoke test, rerun with --allow-missing-langs."
        )
    selected = [lang for lang in required if lang in installed]
    if not selected:
        raise SystemExit("None of the requested Tesseract languages are installed")
    return selected, missing


def parse_pages(value: str | None) -> set[int] | None:
    if not value:
        return None
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            if end < start:
                raise ValueError(f"Invalid page range: {part}")
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return pages


def scan_number(path: str) -> int:
    match = re.search(r"_(\d{4})\.jp2$", path)
    if not match:
        raise ValueError(f"Could not parse scan number from {path}")
    return int(match.group(1))


def archive_iiif_url(archive_id: str, zip_path: str, width: int) -> str:
    # Internet Archive IIIF v3 path shape:
    # item/item_jp2.zip/item_jp2/item_0000.jp2/full/1200,/0/default.jpg
    item_dir = f"{archive_id}_jp2"
    image_name = Path(zip_path).name
    encoded = f"{archive_id}%2F{archive_id}_jp2.zip%2F{item_dir}%2F{image_name}"
    return f"https://iiif.archive.org/image/iiif/3/{encoded}/full/{width},/0/default.jpg"


def jp2_members(zip_file: Path) -> list[str]:
    with zipfile.ZipFile(zip_file) as zf:
        members = [name for name in zf.namelist() if name.endswith(".jp2")]
    return sorted(members, key=scan_number)


def extract_member(zip_file: Path, member: str, target: Path) -> None:
    with zipfile.ZipFile(zip_file) as zf:
        target.write_bytes(zf.read(member))


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    result = run_command(["identify", "-format", "%w %h", str(path)], timeout=60)
    if result.returncode != 0:
        return None, None
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return None, None
    return int(parts[0]), int(parts[1])


def read_optional(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def confidence_values(hocr: str) -> list[float]:
    return [float(value) for value in WORD_CONF_RE.findall(hocr) if float(value) >= 0]


def average_confidence(hocr: str) -> float | None:
    values = confidence_values(hocr)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def class_names(elem: ET.Element) -> set[str]:
    return set((elem.attrib.get("class") or "").split())


def parse_bbox(title: str | None) -> tuple[int, int, int, int] | None:
    if not title:
        return None
    match = BBOX_RE.search(title)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def words_in(elem: ET.Element) -> list[ET.Element]:
    return [child for child in elem.iter() if "ocrx_word" in class_names(child)]


def text_in(elem: ET.Element) -> str:
    return " ".join(" ".join(word.itertext()).strip() for word in words_in(elem)).strip()


def elem_confidence(elem: ET.Element) -> tuple[float | None, int]:
    confs = []
    for word in words_in(elem):
        match = WORD_CONF_RE.search(word.attrib.get("title", ""))
        if match:
            conf = float(match.group(1))
            if conf >= 0:
                confs.append(conf)
    if not confs:
        return None, 0
    return round(sum(confs) / len(confs), 2), len(confs)


def weak_regions(hocr: str, min_confidence: float, min_words: int, max_regions: int) -> list[WeakRegion]:
    try:
        root = ET.fromstring(hocr.encode("utf-8"))
    except ET.ParseError:
        return []
    regions = []
    for elem in root.iter():
        if "ocr_carea" not in class_names(elem):
            continue
        bbox = parse_bbox(elem.attrib.get("title"))
        avg_conf, word_count = elem_confidence(elem)
        if bbox is None or avg_conf is None or word_count < min_words:
            continue
        if avg_conf < min_confidence:
            regions.append(
                WeakRegion(
                    index=len(regions) + 1,
                    bbox=bbox,
                    avg_conf=avg_conf,
                    word_count=word_count,
                    text=text_in(elem),
                )
            )
    regions.sort(key=lambda region: (region.avg_conf, -region.word_count))
    return regions[:max_regions]


def ordered_blocks(hocr: str) -> list[WeakRegion]:
    try:
        root = ET.fromstring(hocr.encode("utf-8"))
    except ET.ParseError:
        return []
    blocks = []
    for elem in root.iter():
        if "ocr_carea" not in class_names(elem):
            continue
        bbox = parse_bbox(elem.attrib.get("title"))
        avg_conf, word_count = elem_confidence(elem)
        if bbox is None:
            continue
        blocks.append(
            WeakRegion(
                index=len(blocks) + 1,
                bbox=bbox,
                avg_conf=avg_conf if avg_conf is not None else -1,
                word_count=word_count,
                text=text_in(elem),
            )
        )
    blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
    return blocks


def run_tesseract(image: Path, out_base: Path, langs: list[str], psm: int, timeout: int) -> OcrResult:
    lang_string = "+".join(langs)
    hocr_result = run_command(
        ["tesseract", str(image), str(out_base), "-l", lang_string, "--psm", str(psm), "hocr"],
        timeout=timeout,
    )
    if hocr_result.returncode != 0:
        raise RuntimeError(hocr_result.stderr.strip() or f"Tesseract hOCR failed for {image}")
    txt_result = run_command(
        ["tesseract", str(image), str(out_base), "-l", lang_string, "--psm", str(psm)],
        timeout=timeout,
    )
    if txt_result.returncode != 0:
        raise RuntimeError(txt_result.stderr.strip() or f"Tesseract text failed for {image}")
    hocr = read_optional(out_base.with_suffix(".hocr"))
    text = read_optional(out_base.with_suffix(".txt"))
    return OcrResult(
        hocr=hocr,
        text=text,
        avg_conf=average_confidence(hocr),
        word_count=len(confidence_values(hocr)),
    )


def crop_region(image: Path, bbox: tuple[int, int, int, int], target: Path, pad: int) -> None:
    x1, y1, x2, y2 = bbox
    x = max(0, x1 - pad)
    y = max(0, y1 - pad)
    width = max(1, (x2 - x1) + (pad * 2))
    height = max(1, (y2 - y1) + (pad * 2))
    result = run_command(
        ["convert", str(image), "-crop", f"{width}x{height}+{x}+{y}", "+repage", str(target)],
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"convert crop failed for {image}")


def profile_langs(profile_langs: list[str], installed_langs: list[str]) -> list[str]:
    return [lang for lang in profile_langs if lang in installed_langs]


def best_region_retry(
    crop: Path,
    region_dir: Path,
    stem: str,
    region: WeakRegion,
    installed_langs: list[str],
    timeout: int,
) -> dict:
    attempts = []
    for profile_name, langs in SCRIPT_PROFILES:
        selected = profile_langs(langs, installed_langs)
        if not selected:
            continue
        out_base = region_dir / f"{stem}_r{region.index:02d}_{profile_name}"
        try:
            result = run_tesseract(crop, out_base, selected, psm=6, timeout=timeout)
        except RuntimeError as exc:
            attempts.append({"profile": profile_name, "langs": selected, "error": str(exc)})
            continue
        attempts.append(
            {
                "profile": profile_name,
                "langs": selected,
                "hocr": str(out_base.with_suffix(".hocr")),
                "text": str(out_base.with_suffix(".txt")),
                "avg_conf": result.avg_conf,
                "word_count": result.word_count,
            }
        )
    successful = [attempt for attempt in attempts if "avg_conf" in attempt and attempt["avg_conf"] is not None]
    best = max(successful, key=lambda item: item["avg_conf"], default=None)
    return {
        "region_index": region.index,
        "bbox": region.bbox,
        "original_avg_conf": region.avg_conf,
        "original_word_count": region.word_count,
        "original_text": region.text,
        "attempts": attempts,
        "best": best,
    }


def refined_text_from_blocks(blocks: list[WeakRegion], retries: list[dict], improvement: float) -> str:
    replacements = {}
    for retry in retries:
        best = retry.get("best")
        if not best:
            continue
        original = retry.get("original_avg_conf")
        improved = best.get("avg_conf")
        text_path = best.get("text")
        if original is None or improved is None or not text_path:
            continue
        if improved >= original + improvement:
            replacements[retry["region_index"]] = read_optional(Path(text_path)).strip()

    out = []
    for block in blocks:
        text = replacements.get(block.index, block.text)
        if text:
            out.append(text)
    return "\n\n".join(out).strip() + "\n"


def page_done(pass1_dir: Path, refined_dir: Path, stem: str) -> bool:
    return (pass1_dir / f"{stem}.hocr").exists() and (refined_dir / f"{stem}.txt").exists()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def process_page(
    *,
    zip_file: Path,
    member: str,
    out_dir: Path,
    archive_id: str,
    iiif_width: int,
    langs: list[str],
    force: bool,
    min_confidence: float,
    min_region_words: int,
    max_regions: int,
    crop_pad: int,
    improvement: float,
    timeout: int,
) -> dict:
    scan = scan_number(member)
    stem = Path(member).stem
    pass1_dir = out_dir / "pass1"
    region_dir = out_dir / "pass2_regions"
    refined_dir = out_dir / "refined"
    pass1_dir.mkdir(parents=True, exist_ok=True)
    region_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "scan": scan,
        "image_id": stem,
        "zip_member": member,
        "iiif": archive_iiif_url(archive_id, member, iiif_width),
        "status": "pending",
        "langs": langs,
    }
    if page_done(pass1_dir, refined_dir, stem) and not force:
        cached_meta = {}
        cached_json = refined_dir / f"{stem}.json"
        if cached_json.exists():
            try:
                cached_meta = json.loads(cached_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cached_meta = {}
        entry.update(
            {
                "status": "cached",
                "pass1_hocr": str(pass1_dir / f"{stem}.hocr"),
                "pass1_text": str(pass1_dir / f"{stem}.txt"),
                "pass1_avg_conf": cached_meta.get("pass1_avg_conf"),
                "pass1_word_count": cached_meta.get("pass1_word_count"),
                "weak_region_count": cached_meta.get("weak_region_count"),
                "refined_text": str(refined_dir / f"{stem}.txt"),
                "refined_json": str(cached_json),
            }
        )
        return entry

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="sprengel_ocr_") as tmp_name:
        tmp = Path(tmp_name)
        image = tmp / f"{stem}.jp2"
        extract_member(zip_file, member, image)
        width, height = image_dimensions(image)
        entry["width"] = width
        entry["height"] = height

        pass1_base = pass1_dir / stem
        pass1 = run_tesseract(image, pass1_base, langs, psm=3, timeout=timeout)
        regions = weak_regions(pass1.hocr, min_confidence, min_region_words, max_regions)
        retries = []
        for region in regions:
            crop = tmp / f"{stem}_r{region.index:02d}.png"
            crop_region(image, region.bbox, crop, crop_pad)
            retries.append(best_region_retry(crop, region_dir, stem, region, langs, timeout))

        blocks = ordered_blocks(pass1.hocr)
        refined_text = refined_text_from_blocks(blocks, retries, improvement)
        if not refined_text.strip():
            refined_text = pass1.text.strip() + "\n"

        refined_txt = refined_dir / f"{stem}.txt"
        refined_json = refined_dir / f"{stem}.json"
        refined_txt.write_text(refined_text, encoding="utf-8")
        write_json(
            refined_json,
            {
                "scan": scan,
                "image_id": stem,
                "zip_member": member,
                "langs": langs,
                "pass1_avg_conf": pass1.avg_conf,
                "pass1_word_count": pass1.word_count,
                "weak_region_count": len(regions),
                "retries": retries,
            },
        )

    entry.update(
        {
            "status": "ok",
            "elapsed_seconds": round(time.time() - started, 2),
            "pass1_hocr": str(pass1_dir / f"{stem}.hocr"),
            "pass1_text": str(pass1_dir / f"{stem}.txt"),
            "pass1_avg_conf": pass1.avg_conf,
            "pass1_word_count": pass1.word_count,
            "weak_region_count": len(regions),
            "refined_text": str(refined_txt),
            "refined_json": str(refined_json),
        }
    )
    return entry


def summarize(entries: list[dict], missing_langs: list[str], out_dir: Path) -> dict:
    processed = [entry for entry in entries if entry["status"] in {"ok", "cached"}]
    failed = [entry for entry in entries if entry["status"] == "error"]
    low_conf = [
        {
            "scan": entry["scan"],
            "image_id": entry["image_id"],
            "pass1_avg_conf": entry.get("pass1_avg_conf"),
            "weak_region_count": entry.get("weak_region_count"),
        }
        for entry in entries
        if entry.get("pass1_avg_conf") is not None and entry.get("pass1_avg_conf") < 65
    ]
    return {
        "output_dir": str(out_dir),
        "processed_or_cached": len(processed),
        "failed": len(failed),
        "not_requested": len([entry for entry in entries if entry["status"] == "not_requested"]),
        "missing_langs": missing_langs,
        "low_confidence_pages": low_conf,
        "errors": [{"scan": entry["scan"], "error": entry.get("error")} for entry in failed],
    }


def image_id_scan(image_id: str) -> int | None:
    try:
        return scan_number(f"{image_id}.jp2")
    except ValueError:
        return None


def build_context(out_dir: Path, entries: list[dict]) -> dict:
    """Build cross-page context for later review/revisit passes.

    This deliberately does not rewrite OCR text. It extracts repeated Latin-ish
    tokens and page-reference patterns from the refined text layer so a later
    correction step can use document context without hiding the raw hOCR.
    """
    refined_dir = out_dir / "refined"
    token_counts: dict[str, int] = {}
    pages = []
    for text_path in sorted(refined_dir.glob("*.txt")):
        image_id = text_path.stem
        scan = image_id_scan(image_id)
        text = text_path.read_text(encoding="utf-8", errors="replace")
        tokens = LATIN_TOKEN_RE.findall(text)
        page_refs = PAGE_REF_RE.findall(text)
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
        headings = [
            line.strip()
            for line in text.splitlines()
            if line.strip().isupper() and 3 <= len(line.strip()) <= 80
        ][:5]
        pages.append(
            {
                "scan": scan,
                "image_id": image_id,
                "token_count": len(tokens),
                "page_ref_count": len(page_refs),
                "sample_page_refs": page_refs[:20],
                "headings": headings,
            }
        )

    repeated_tokens = [
        {"token": token, "count": count}
        for token, count in sorted(token_counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= 2
    ][:500]
    revisit_pages = [
        {
            "scan": entry["scan"],
            "image_id": entry["image_id"],
            "reason": "low-confidence or weak-region page",
            "pass1_avg_conf": entry.get("pass1_avg_conf"),
            "weak_region_count": entry.get("weak_region_count"),
        }
        for entry in entries
        if entry.get("status") in {"ok", "cached"}
        and (
            (entry.get("pass1_avg_conf") is not None and entry.get("pass1_avg_conf") < 65)
            or (entry.get("weak_region_count") or 0) > 0
        )
    ]
    return {
        "refined_pages_seen": len(pages),
        "repeated_latin_tokens": repeated_tokens,
        "pages": pages,
        "revisit_pages": revisit_pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", default=DEFAULT_ZIP, type=Path, help="JP2 zip to OCR")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT, type=Path)
    parser.add_argument("--archive-id", default="b23982500_0002")
    parser.add_argument("--iiif-width", default=1200, type=int)
    parser.add_argument("--pages", help="Scan numbers to run, e.g. 700 or 690-705")
    parser.add_argument("--langs", default="+".join(DEFAULT_LANGS), help="Tesseract languages, plus-separated")
    parser.add_argument("--allow-missing-langs", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-run pages with existing output")
    parser.add_argument("--min-confidence", default=65.0, type=float)
    parser.add_argument("--min-region-words", default=3, type=int)
    parser.add_argument("--max-regions", default=8, type=int)
    parser.add_argument("--crop-pad", default=20, type=int)
    parser.add_argument("--improvement", default=5.0, type=float)
    parser.add_argument("--timeout", default=300, type=int, help="Per-Tesseract-call timeout in seconds")
    parser.add_argument("--workers", default=1, type=int, help="Parallel page workers")
    args = parser.parse_args()

    require_command("tesseract")
    require_command("identify")
    require_command("convert")

    if not args.zip.exists():
        raise SystemExit(f"JP2 zip not found: {args.zip}")
    requested = parse_pages(args.pages)
    required_langs = [part for part in args.langs.split("+") if part]
    langs, missing_langs = select_langs(required_langs, args.allow_missing_langs)
    members = jp2_members(args.zip)
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    entries_by_scan = {}
    work_members = []
    for member in members:
        scan = scan_number(member)
        if requested is not None and scan not in requested:
            entries_by_scan[scan] = {
                "scan": scan,
                "image_id": Path(member).stem,
                "zip_member": member,
                "iiif": archive_iiif_url(args.archive_id, member, args.iiif_width),
                "status": "not_requested",
            }
        else:
            work_members.append(member)

    def run_member(member: str) -> dict:
        scan = scan_number(member)
        try:
            return process_page(
                zip_file=args.zip,
                member=member,
                out_dir=args.output_dir,
                archive_id=args.archive_id,
                iiif_width=args.iiif_width,
                langs=langs,
                force=args.force,
                min_confidence=args.min_confidence,
                min_region_words=args.min_region_words,
                max_regions=args.max_regions,
                crop_pad=args.crop_pad,
                improvement=args.improvement,
                timeout=args.timeout,
            )
        except Exception as exc:  # Keep full runs resumable.
            return {
                "scan": scan,
                "image_id": Path(member).stem,
                "zip_member": member,
                "iiif": archive_iiif_url(args.archive_id, member, args.iiif_width),
                "status": "error",
                "error": str(exc),
            }

    completed = 0
    total_to_run = len(work_members)
    if args.workers == 1:
        for member in work_members:
            scan = scan_number(member)
            print(f"OCR {completed + 1}/{total_to_run}: scan {scan:04d}", flush=True)
            entry = run_member(member)
            completed += 1
            entries_by_scan[entry["scan"]] = entry
            entries = [entries_by_scan[scan_number(member)] for member in members if scan_number(member) in entries_by_scan]
            write_json(args.output_dir / "manifest.json", {"pages": entries})
            write_json(args.output_dir / "qa.json", summarize(entries, missing_langs, args.output_dir))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_member, member): member for member in work_members}
            for future in as_completed(futures):
                member = futures[future]
                scan = scan_number(member)
                entry = future.result()
                completed += 1
                entries_by_scan[entry["scan"]] = entry
                print(
                    f"OCR {completed}/{total_to_run}: scan {scan:04d} -> {entry['status']}",
                    flush=True,
                )
                entries = [entries_by_scan[scan_number(member)] for member in members if scan_number(member) in entries_by_scan]
                write_json(args.output_dir / "manifest.json", {"pages": entries})
                write_json(args.output_dir / "qa.json", summarize(entries, missing_langs, args.output_dir))

    entries = [entries_by_scan[scan_number(member)] for member in members if scan_number(member) in entries_by_scan]

    manifest = {
        "source_zip": str(args.zip),
        "archive_id": args.archive_id,
        "iiif_width": args.iiif_width,
        "requested_pages": sorted(requested) if requested else None,
        "langs": langs,
        "missing_langs": missing_langs,
        "page_count": len(members),
        "pages": entries,
    }
    write_json(args.output_dir / "manifest.json", manifest)
    write_json(args.output_dir / "qa.json", summarize(entries, missing_langs, args.output_dir))
    write_json(args.output_dir / "context.json", build_context(args.output_dir, entries))
    print(f"Wrote {args.output_dir / 'manifest.json'}")
    print(f"Wrote {args.output_dir / 'qa.json'}")
    print(f"Wrote {args.output_dir / 'context.json'}")
    if any(entry["status"] == "error" for entry in entries):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
