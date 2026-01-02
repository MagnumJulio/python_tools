#!/usr/bin/env python3
"""
Extract quoted variable codes from text (clipboard / file / stdin).

Usage:
  - From clipboard (default): python scrappings/scrapy.py
  - From a file:              python scrappings/scrapy.py --file page.html
  - From stdin:               cat page.html | python scrappings/scrapy.py --stdin
  - Copy results to clipboard: python scrappings/scrapy.py --copy
  - Custom regex:             python scrappings/scrapy.py --pattern '"([A-Z0-9_\\-]{4,})"'
"""
from __future__ import annotations
import re
import sys
import argparse

try:
    import pyperclip
    HAVE_PYPERCLIP = True
except Exception:
    HAVE_PYPERCLIP = False

def read_clipboard() -> str:
    if not HAVE_PYPERCLIP:
        raise RuntimeError("pyperclip not available")
    return pyperclip.paste()

def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def read_stdin() -> str:
    return sys.stdin.read()

def extract_ids(text: str, pattern: str) -> list[str]:
    rx = re.compile(pattern)
    return rx.findall(text)

def uniq_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out

def main() -> None:
    p = argparse.ArgumentParser(description="Extract quoted variable codes from text")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--file", "-f", help="Read text from file")
    group.add_argument("--stdin", action="store_true", help="Read text from stdin")
    group.add_argument("--clipboard", "-c", action="store_true", help="Read text from clipboard (explicit)")
    p.add_argument("--pattern", "-p",
                   default=r'"[a-zA-Z0-9]+_[a-zA-Z0-9]+_[a-zA-Z0-9]+(?:_[a-zA-Z0-9]+)?"',
                   help="Regex pattern to capture identifiers (default matches uppercase+digits+_/- inside double quotes)")
    p.add_argument("--copy", action="store_true", help="Copy results back to clipboard")
    args = p.parse_args()

    try:
        if args.file:
            text = read_file(args.file)
        elif args.stdin:
            text = read_stdin()
        else:
            try:
                text = read_clipboard()
            except Exception:
                if not sys.stdin.isatty():
                    text = read_stdin()
                else:
                    p.error("No input: copy page to clipboard or use --file/--stdin")
    except Exception as e:
        sys.exit(f"Error reading input: {e}")

    ids = extract_ids(text, args.pattern)
    ids = uniq_keep_order(ids)

    if not ids:
        print("No identifiers found.", file=sys.stderr)
        sys.exit(0)

    out = "\n".join(ids)
    print(out)

    if args.copy:
        if not HAVE_PYPERCLIP:
            print("pyperclip not installed; cannot copy to clipboard.", file=sys.stderr)
        else:
            pyperclip.copy(out)

if __name__ == "__main__":
    main()