#!/usr/bin/env python3
"""
Remove spaces and newlines from text in the clipboard.

Usage:
  - From clipboard (default): python cutclip.py
"""
from __future__ import annotations
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

def process_text(text: str) -> str:
    return "".join(text.split())

def main() -> None:
    p = argparse.ArgumentParser(description="Remove spaces and newlines from text in the clipboard")
    args = p.parse_args()

    try:
        text = read_clipboard()
    except Exception as e:
        sys.exit(f"Error reading clipboard: {e}")

    processed_text = process_text(text)

    print(processed_text)

    if not HAVE_PYPERCLIP:
        print("pyperclip not installed; cannot copy to clipboard.", file=sys.stderr)
    else:
        pyperclip.copy(processed_text)

if __name__ == "__main__":
    main()