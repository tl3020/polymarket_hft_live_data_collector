"""Batch convert JSONL files to hftbacktest NPZ.

Scans data directory for JSONL/JSONL.gz files and converts each to NPZ.

Usage:
    python -m converter.batch_convert --data-dir ./data --output-dir ./npz
    python -m converter.batch_convert --data-dir ./data --output-dir ./npz --verify
"""

import argparse
import glob
import os
import sys

from .jsonl_to_npz import convert_jsonl_to_npz
from .verify_npz import verify_npz


def batch_convert(data_dir: str, output_dir: str, verify: bool = False):
    """Convert all JSONL files in data_dir to NPZ in output_dir."""
    patterns = [
        os.path.join(data_dir, "**", "*.jsonl.gz"),
        os.path.join(data_dir, "**", "*.jsonl"),
    ]

    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern, recursive=True))

    # Deduplicate (if both .jsonl and .jsonl.gz exist, prefer .gz)
    seen_bases = set()
    unique_files = []
    for f in sorted(files):
        base = f.replace(".gz", "")
        if base not in seen_bases:
            seen_bases.add(base)
            unique_files.append(f)

    if not unique_files:
        print(f"No JSONL files found in {data_dir}")
        return

    print(f"Found {len(unique_files)} JSONL files to convert")
    print(f"Output directory: {output_dir}")
    print()

    success = 0
    failed = 0
    skipped = 0

    for i, input_path in enumerate(unique_files):
        # Compute output path preserving directory structure
        rel = os.path.relpath(input_path, data_dir)
        for ext in (".gz", ".jsonl"):
            if rel.endswith(ext):
                rel = rel[:-len(ext)]
        out_path = os.path.join(output_dir, rel + ".npz")

        # Skip if already converted
        if os.path.exists(out_path):
            skipped += 1
            continue

        print(f"\n[{i+1}/{len(unique_files)}] {rel}")
        try:
            convert_jsonl_to_npz(input_path, out_path)

            if verify:
                ok = verify_npz(out_path)
                if not ok:
                    print(f"  VERIFY FAILED: {out_path}")
                    failed += 1
                    continue

            success += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {success} success, {failed} failed, {skipped} skipped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch convert JSONL to NPZ")
    parser.add_argument("--data-dir", required=True, help="Input JSONL directory")
    parser.add_argument("--output-dir", required=True, help="Output NPZ directory")
    parser.add_argument("--verify", action="store_true", help="Verify each NPZ after conversion")
    args = parser.parse_args()

    batch_convert(args.data_dir, args.output_dir, args.verify)
