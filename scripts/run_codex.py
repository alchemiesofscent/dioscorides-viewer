#!/usr/bin/env python3
"""
Phase 4: Main Codex CLI production loop.

Usage:
    # Dry run (print prompts, don't call codex):
    python3 scripts/run_codex.py --manifest manifest.json --scaffold scaffold.json \
        --ocr-dir ocr/raw --xml-baseline ocr/xml_baseline.json \
        --images-dir images/raw --system-prompt prompts/system.md \
        --output-dir chunks --dry-run

    # Pilot (specific chunks):
    python3 scripts/run_codex.py ... --chunk-ids book1_001,book3_001

    # Page pilot (writes chunks/pilots/pg_0184.xml):
    python3 scripts/run_codex.py ... --pdf-pages 184

    # Full batch:
    python3 scripts/run_codex.py ... --max-parallel 4

Assembles per-chunk prompts with OCR text, XML baseline, scaffold slice,
then calls `codex exec -i <images>` with the prompt on stdin for each chunk.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
from page_map import pdf_to_book_page


def load_text_file(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    return ""


def get_scaffold_for_pages(scaffold, pages):
    """Extract scaffold entries relevant to the given book pages."""
    page_set = set(str(p) for p in pages)
    relevant = []
    for ch in scaffold.get("chapters", []):
        if ch.get("page") in page_set:
            relevant.append(ch)
    # Also include chapters that might span into these pages
    # (chapters starting on preceding pages)
    if not relevant and scaffold.get("chapters"):
        # Find chapters near these pages
        for ch in scaffold["chapters"]:
            try:
                ch_page = int(ch.get("page", 0))
                for p in pages:
                    try:
                        if abs(ch_page - int(p)) <= 2:
                            relevant.append(ch)
                            break
                    except (ValueError, TypeError):
                        pass
            except (ValueError, TypeError):
                pass
    return relevant


def assemble_prompt(chunk, scaffold, ocr_dir, xml_baseline, footnote_ocr_dir=None):
    """Build the full prompt text for a chunk."""
    parts = []
    parts.append("Transcribe the following %d page images into diplomatic TEI XML." % chunk["page_count"])
    parts.append("")
    parts.append("Pages: book pages %s" % ", ".join(str(p) for p in chunk["pages"]))
    parts.append("Section: %s" % chunk["section"])
    parts.append("")

    # Scaffold
    scaffold_slice = get_scaffold_for_pages(scaffold, chunk["pages"])
    if scaffold_slice:
        parts.append("## Expected chapter structure on these pages:")
        parts.append("```json")
        parts.append(json.dumps(scaffold_slice, indent=2, ensure_ascii=False))
        parts.append("```")
        parts.append("")

    # OCR text per page
    parts.append("## Tesseract OCR text (noisy baseline):")
    for pdf_p, bp in zip(chunk["pdf_pages"], chunk["pages"]):
        ocr_file = os.path.join(ocr_dir, "pg_%04d.txt" % pdf_p)
        ocr_text = load_text_file(ocr_file)
        if ocr_text:
            parts.append("")
            parts.append("### Page %s (OCR):" % bp)
            parts.append("```")
            parts.append(ocr_text[:3000])  # Cap to avoid context overflow
            parts.append("```")

    # XML baseline text per page
    if xml_baseline:
        parts.append("")
        parts.append("## Existing XML text (reference, may have errors):")
        for bp in chunk["pages"]:
            xml_text = xml_baseline.get(str(bp), "")
            if xml_text:
                parts.append("")
                parts.append("### Page %s (XML):" % bp)
                parts.append("```")
                parts.append(xml_text[:3000])
                parts.append("```")

    # Footnote OCR
    if footnote_ocr_dir:
        parts.append("")
        parts.append("## Footnote OCR (enhanced, from bottom of page):")
        for pdf_p, bp in zip(chunk["pdf_pages"], chunk["pages"]):
            fn_file = os.path.join(footnote_ocr_dir, "pg_%04d_fn.txt" % pdf_p)
            fn_text = load_text_file(fn_file)
            if fn_text:
                parts.append("")
                parts.append("### Page %s footnotes:" % bp)
                parts.append("```")
                parts.append(fn_text[:1500])
                parts.append("```")

    parts.append("")
    parts.append("Produce the TEI XML fragment now. Output ONLY XML, no explanation.")
    return "\n".join(parts)


def parse_csv_ints(value):
    """Parse a comma-separated list of integers."""
    out = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(int(item))
        except ValueError as e:
            raise ValueError("expected integer page number, got %r" % item) from e
    return out


def build_pdf_page_pilots(manifest, pdf_pages):
    """Build one-page pilot chunks from manifest page metadata."""
    pages_by_pdf = {int(p["pdf_page"]): p for p in manifest["pages"]}
    chunks = []
    missing = []

    for pdf_page in pdf_pages:
        page = pages_by_pdf.get(pdf_page)
        if not page:
            missing.append(pdf_page)
            continue

        chunks.append({
            "id": "pg_%04d" % pdf_page,
            "section": page["section"] or "unknown",
            "output_section": "pilots",
            "section_type": "pilot",
            "pages": [page["book_page"]],
            "pdf_pages": [page["pdf_page"]],
            "images": [page["image"]],
            "facs": [page["facs"]],
            "page_count": 1,
        })

    if missing:
        raise ValueError("PDF page(s) not found in manifest text pages: %s" % (
            ", ".join(str(p) for p in missing)
        ))

    return chunks


def run_codex_chunk(chunk, prompt, images_dir, system_prompt_path, output_dir, model, dry_run=False):
    """Run codex CLI for a single chunk."""
    chunk_id = chunk["id"]
    section = chunk.get("output_section", chunk["section"])

    # Build output path
    out_subdir = os.path.join(output_dir, section)
    os.makedirs(out_subdir, exist_ok=True)
    out_file = os.path.join(out_subdir, "%s.xml" % chunk_id)

    if dry_run:
        # Write prompt to file for review
        prompt_file = os.path.join(out_subdir, "%s_prompt.txt" % chunk_id)
        with open(prompt_file, "w") as f:
            f.write(prompt)
        return {"chunk_id": chunk_id, "status": "dry_run", "prompt_file": prompt_file}

    # Build codex command
    response_path = None
    response_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix=f"{chunk_id}_", delete=False
    )
    response_path = response_file.name
    response_file.close()

    cmd = [
        "codex", "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color", "never",
        "--output-last-message", response_path,
    ]
    if model:
        cmd.extend(["--model", model])

    # Add images
    for img_name in chunk["images"]:
        img_path = os.path.join(images_dir, img_name)
        if os.path.exists(img_path):
            cmd.extend(["-i", img_path])

    # Add system prompt as context via wrapping in the prompt itself
    system_text = load_text_file(system_prompt_path)

    full_prompt = system_text + "\n\n---\n\n" + prompt
    cmd.extend(["--", full_prompt])

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            return {
                "chunk_id": chunk_id,
                "status": "error",
                "elapsed": round(elapsed, 1),
                "error": (result.stderr or result.stdout).strip()[-2000:],
            }

        output = load_text_file(response_path) or result.stdout.strip()

        # Extract XML from output (codex may wrap in markdown fences)
        if "```xml" in output:
            xml_start = output.index("```xml") + 6
            xml_end = output.index("```", xml_start)
            output = output[xml_start:xml_end].strip()
        elif "```" in output:
            xml_start = output.index("```") + 3
            xml_end = output.index("```", xml_start)
            output = output[xml_start:xml_end].strip()

        output = output.replace("ϑ", "θ")

        with open(out_file, "w", encoding="utf-8") as f:
            f.write(output)

        return {
            "chunk_id": chunk_id,
            "status": "success",
            "output_file": out_file,
            "elapsed": round(elapsed, 1),
            "output_len": len(output),
        }
    except subprocess.TimeoutExpired:
        return {"chunk_id": chunk_id, "status": "timeout"}
    except Exception as e:
        return {"chunk_id": chunk_id, "status": "error", "error": str(e)}
    finally:
        if response_path:
            try:
                os.unlink(response_path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--scaffold", required=True)
    parser.add_argument("--ocr-dir", required=True)
    parser.add_argument("--xml-baseline", required=True)
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--output-dir", default="chunks")
    parser.add_argument("--footnote-ocr-dir", default=None)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--chunk-ids", default=None,
                        help="Comma-separated chunk IDs to process (default: all)")
    parser.add_argument("--pdf-pages", default=None,
                        help="Comma-separated PDF page numbers for one-page pilot chunks")
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true",
                        help="Write prompts to files without calling codex")
    args = parser.parse_args()

    with open(args.manifest) as f:
        manifest = json.load(f)
    with open(args.scaffold) as f:
        scaffold = json.load(f)

    xml_baseline = {}
    if os.path.exists(args.xml_baseline):
        with open(args.xml_baseline) as f:
            xml_baseline = json.load(f)

    if args.chunk_ids and args.pdf_pages:
        parser.error("--chunk-ids and --pdf-pages are mutually exclusive")

    chunks = manifest["chunks"]
    if args.pdf_pages:
        try:
            chunks = build_pdf_page_pilots(manifest, parse_csv_ints(args.pdf_pages))
        except ValueError as e:
            parser.error(str(e))
    if args.chunk_ids:
        selected = set(args.chunk_ids.split(","))
        chunks = [c for c in chunks if c["id"] in selected]

    print("Processing %d chunks (%s)" % (len(chunks), "dry run" if args.dry_run else "live"))

    # Assemble all prompts
    tasks = []
    for chunk in chunks:
        prompt = assemble_prompt(
            chunk, scaffold, args.ocr_dir, xml_baseline, args.footnote_ocr_dir
        )
        tasks.append((chunk, prompt))

    results = []
    if args.max_parallel <= 1 or args.dry_run:
        for chunk, prompt in tasks:
            r = run_codex_chunk(
                chunk, prompt, args.images_dir, args.system_prompt,
                args.output_dir, args.model, args.dry_run
            )
            results.append(r)
            print("  %s: %s" % (r["chunk_id"], r["status"]))
    else:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
            futures = {}
            for chunk, prompt in tasks:
                fut = pool.submit(
                    run_codex_chunk,
                    chunk, prompt, args.images_dir, args.system_prompt,
                    args.output_dir, args.model, args.dry_run
                )
                futures[fut] = chunk["id"]
            for fut in as_completed(futures):
                r = fut.result()
                results.append(r)
                print("  %s: %s" % (r["chunk_id"], r["status"]))

    # Write log
    log_path = os.path.join(args.output_dir, "run_log.json")
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2)

    success = sum(1 for r in results if r["status"] == "success")
    print("\nDone. %d/%d succeeded. Log: %s" % (success, len(results), log_path))


if __name__ == "__main__":
    main()
