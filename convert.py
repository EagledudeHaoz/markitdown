#!/usr/bin/env python3
"""
markitdown_batch — a batch conversion system built on Microsoft's MarkItDown.

Converts a single file OR an entire folder tree (any mix of file types) into
Markdown, preserving the folder structure in the output directory.

Supported input types come from MarkItDown itself: PDF, Word, PowerPoint,
Excel, images (EXIF + OCR), audio (EXIF + speech transcription), HTML, CSV/
JSON/XML, ZIP (recurses into contents), EPUB, YouTube URLs, and more.

USAGE
-----
Convert a single file:
    python convert.py path/to/file.pdf

Convert an entire folder (recursively) into ./output mirroring structure:
    python convert.py path/to/folder -o output

Convert a folder, skip files already converted, write a summary log:
    python convert.py path/to/folder -o output --skip-existing --log run.log

Enable LLM-generated image descriptions (requires an OpenAI-compatible key):
    export OPENAI_API_KEY=sk-...
    python convert.py path/to/folder -o output --llm-images --llm-model gpt-4o

Use Azure Document Intelligence for higher-fidelity PDF/scan conversion:
    python convert.py file.pdf -o output --docintel-endpoint https://<resource>.cognitiveservices.azure.com/

Use Azure Content Understanding (docs, audio, AND video in one pipeline):
    python convert.py folder -o output --cu-endpoint https://<resource>.cognitiveservices.azure.com/

List every file MarkItDown will attempt vs. skip, without converting:
    python convert.py path/to/folder --dry-run
"""

import argparse
import concurrent.futures
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from markitdown import MarkItDown

# Extensions MarkItDown does not claim to handle. We still *try* every file
# (MarkItDown will raise cleanly if unsupported) but we skip these outright
# to avoid noisy, guaranteed-failure attempts and wasted time.
DEFAULT_SKIP_EXTENSIONS = {
    ".exe", ".dll", ".so", ".bin", ".pyc", ".class", ".o", ".a",
    ".git", ".gitignore", ".ds_store", ".lock",
}

MARKDOWN_EXT = ".md"


@dataclass
class ConversionResult:
    source: str
    output: Optional[str]
    status: str  # "ok" | "skipped" | "error"
    detail: str = ""
    seconds: float = 0.0


@dataclass
class RunSummary:
    results: list = field(default_factory=list)

    def add(self, r: ConversionResult):
        self.results.append(r)

    def counts(self):
        ok = sum(1 for r in self.results if r.status == "ok")
        skipped = sum(1 for r in self.results if r.status == "skipped")
        errors = sum(1 for r in self.results if r.status == "error")
        return ok, skipped, errors

    def print_summary(self):
        ok, skipped, errors = self.counts()
        total = len(self.results)
        print("\n" + "=" * 60)
        print(f"MarkItDown batch run complete: {total} file(s) scanned")
        print(f"  converted : {ok}")
        print(f"  skipped   : {skipped}")
        print(f"  errors    : {errors}")
        print("=" * 60)
        if errors:
            print("\nFiles that failed:")
            for r in self.results:
                if r.status == "error":
                    print(f"  - {r.source}: {r.detail}")

    def write_log(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([r.__dict__ for r in self.results], f, indent=2)


def build_markitdown(args) -> MarkItDown:
    kwargs = {"enable_plugins": args.use_plugins}

    if args.docintel_endpoint:
        kwargs["docintel_endpoint"] = args.docintel_endpoint

    if args.cu_endpoint:
        kwargs["cu_endpoint"] = args.cu_endpoint

    if args.llm_images:
        try:
            from openai import OpenAI
        except ImportError:
            print(
                "ERROR: --llm-images requires the 'openai' package. "
                "Install it with: pip install openai",
                file=sys.stderr,
            )
            sys.exit(1)
        kwargs["llm_client"] = OpenAI()
        kwargs["llm_model"] = args.llm_model
        if args.llm_prompt:
            kwargs["llm_prompt"] = args.llm_prompt

    return MarkItDown(**kwargs)


def should_skip(path: Path, skip_exts) -> Optional[str]:
    if path.name.startswith("."):
        return "hidden file"
    if path.suffix.lower() in skip_exts:
        return f"excluded extension ({path.suffix})"
    if path.suffix.lower() == MARKDOWN_EXT:
        return "already markdown"
    return None


def collect_files(root: Path, skip_exts) -> list:
    files = []
    if root.is_file():
        files.append(root)
        return files
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files.append(p)
    return files


def convert_one(md: MarkItDown, src: Path, out_root: Path, in_root: Path, skip_existing: bool) -> ConversionResult:
    start = time.time()

    if in_root.is_dir():
        rel = src.relative_to(in_root)
    else:
        rel = Path(src.name)

    out_path = (out_root / rel).with_suffix(MARKDOWN_EXT)

    if skip_existing and out_path.exists():
        return ConversionResult(str(src), str(out_path), "skipped", "output already exists")

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = md.convert(str(src))
        text = result.markdown if hasattr(result, "markdown") and result.markdown else result.text_content
        out_path.write_text(text or "", encoding="utf-8")
        return ConversionResult(str(src), str(out_path), "ok", seconds=time.time() - start)
    except Exception as e:
        return ConversionResult(str(src), None, "error", f"{type(e).__name__}: {e}", time.time() - start)


def main():
    parser = argparse.ArgumentParser(
        description="Batch-convert any file or folder to Markdown using Microsoft's MarkItDown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", help="File or directory to convert.")
    parser.add_argument("-o", "--output", default="output", help="Output directory (default: ./output).")
    parser.add_argument("--skip-existing", action="store_true", help="Skip files whose .md output already exists.")
    parser.add_argument("--use-plugins", action="store_true", help="Enable installed MarkItDown plugins (e.g. markitdown-ocr).")
    parser.add_argument("--workers", type=int, default=4, help="Parallel worker threads (default: 4).")
    parser.add_argument("--exclude-ext", nargs="*", default=[], help="Extra extensions to skip, e.g. --exclude-ext .tmp .bak")
    parser.add_argument("--dry-run", action="store_true", help="List what would be converted/skipped, without converting.")
    parser.add_argument("--log", default=None, help="Write a JSON log of results to this path.")

    # LLM image descriptions
    parser.add_argument("--llm-images", action="store_true", help="Use an LLM to describe images (pptx/image files). Needs OPENAI_API_KEY.")
    parser.add_argument("--llm-model", default="gpt-4o", help="Model name for --llm-images (default: gpt-4o).")
    parser.add_argument("--llm-prompt", default=None, help="Custom prompt for image descriptions.")

    # Azure options
    parser.add_argument("--docintel-endpoint", default=None, help="Azure Document Intelligence endpoint URL.")
    parser.add_argument("--cu-endpoint", default=None, help="Azure Content Understanding endpoint URL (docs/audio/video).")

    args = parser.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.exists():
        print(f"ERROR: input path does not exist: {in_path}", file=sys.stderr)
        sys.exit(1)

    out_root = Path(args.output).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    skip_exts = set(DEFAULT_SKIP_EXTENSIONS) | {e.lower() if e.startswith(".") else f".{e.lower()}" for e in args.exclude_ext}

    all_files = collect_files(in_path, skip_exts)

    todo, pre_skipped = [], []
    for f in all_files:
        reason = should_skip(f, skip_exts)
        if reason:
            pre_skipped.append((f, reason))
        else:
            todo.append(f)

    print(f"Found {len(all_files)} file(s) under {in_path}")
    print(f"  will attempt : {len(todo)}")
    print(f"  pre-skipped  : {len(pre_skipped)}")

    if args.dry_run:
        print("\n--- DRY RUN: files to convert ---")
        for f in todo:
            print(f"  CONVERT  {f}")
        print("\n--- DRY RUN: files skipped ---")
        for f, reason in pre_skipped:
            print(f"  SKIP     {f}  ({reason})")
        return

    md = build_markitdown(args)
    summary = RunSummary()
    for f, reason in pre_skipped:
        summary.add(ConversionResult(str(f), None, "skipped", reason))

    in_root_for_rel = in_path if in_path.is_dir() else in_path.parent

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(convert_one, md, f, out_root, in_root_for_rel, args.skip_existing): f
            for f in todo
        }
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            r = fut.result()
            summary.add(r)
            status_symbol = {"ok": "✓", "error": "✗", "skipped": "-"}[r.status]
            print(f"[{i}/{len(todo)}] {status_symbol} {r.source}" + (f"  ({r.detail})" if r.status != "ok" else ""))

    summary.print_summary()
    if args.log:
        summary.write_log(args.log)
        print(f"\nLog written to {args.log}")


if __name__ == "__main__":
    main()
