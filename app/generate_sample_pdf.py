#!/usr/bin/env python3
"""Generate sample PDFs using the repository's PDF generator.

Run from repository root:
  python app/generate_sample_pdf.py [--open]

--open will attempt to open the generated PDFs on macOS using `open`.
"""
import argparse
import subprocess
import os
import sys

# Ensure local app package is importable when running from repo root
sys.path.insert(0, os.path.dirname(__file__))
try:
    from printer_mqtt_handler import generate_pdf
except Exception as e:
    print("Failed to import generate_pdf from printer_mqtt_handler:", e)
    raise


SAMPLES = [
    (
        "Shopping List",
        "- [ ] Apples\n- [ ] Bread\n- [ ] Milk\n- [ ] Butter",
    ),
    (
        "Long Line Test",
        "This is a very long line intended to wrap across multiple visual lines to test indentation and avoid clipping: HDMI extender on smart plug - to control heat?",
    ),
    (
        "Mixed Items",
        "- Item one with wrapping that should indent properly when it wraps to another line\nNormal paragraph line\n- [ ] Another checkbox item that might wrap to see proper indentation\n- [ ] Final item",
    ),
]


def main(open_files=False):
    out_paths = []
    for i, (title, message) in enumerate(SAMPLES, start=1):
        print(f"Generating sample {i}: {title}")
        path = generate_pdf(title, message)
        print(" ->", path)
        out_paths.append(path)
        if open_files and path:
            try:
                subprocess.run(["open", path], check=False)
            except Exception as e:
                print("Failed to open PDF:", e)

    print("Generated files:")
    for p in out_paths:
        print("  ", p)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="Open generated PDFs (macOS `open`)")
    args = parser.parse_args()
    main(open_files=args.open)
