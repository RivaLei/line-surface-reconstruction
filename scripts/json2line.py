#!/usr/bin/env python3
"""Convert residual-line JSON files to Wavefront OBJ vertices and lines.

Usage:
    python3 scripts/json2line.py
    python3 scripts/json2line.py data/Barn
    python3 scripts/json2line.py data/Barn/input_lines_from_residuals.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def convert(source: Path) -> tuple[Path, int]:
    """Write two vertices and one 1-based OBJ line per input segment."""
    with source.open(encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or not isinstance(document.get("lines"), list):
        raise ValueError("expected a JSON object containing a 'lines' array")
    lines = document["lines"]
    # Validate before opening the output so malformed input does not truncate it.
    for index, line in enumerate(lines):
        for key in ("pt1", "pt2"):
            point = line.get(key) if isinstance(line, dict) else None
            if (not isinstance(point, list) or len(point) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) for v in point)):
                raise ValueError(f"lines[{index}].{key}: expected three finite coordinates")
    destination = source.with_suffix(".obj")
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"# {len(lines)} line segments\n")
        for line in lines:
            for key in ("pt1", "pt2"):
                stream.write("v " + " ".join(format(v, ".17g") for v in line[key]) + "\n")
        for index in range(len(lines)):
            stream.write(f"l {2 * index + 1} {2 * index + 2}\n")
    return destination, len(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data",
                        help="JSON file or directory to search recursively (default: project data)")
    args = parser.parse_args()
    if args.input.is_file():
        sources = [args.input]
    elif args.input.is_dir():
        sources = sorted(args.input.rglob("input_lines_from_residuals.json"))
    else:
        parser.error(f"input does not exist: {args.input}")
    if not sources:
        parser.error(f"no input_lines_from_residuals.json files found under {args.input}")
    failed = 0
    for source in sources:
        try:
            destination, count = convert(source)
            print(f"{source} -> {destination} ({count} lines, {2 * count} vertices)")
        except (OSError, ValueError, OverflowError) as error:
            print(f"ERROR {source}: {error}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
