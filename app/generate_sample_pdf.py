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
    from printer_mqtt_handler import generate_pdf, resolve_formatting, BUILTIN_DEFAULTS
except Exception as e:
    print("Failed to import from printer_mqtt_handler:", e)
    raise


def _fmt(overrides=None):
    """Return a formatting dict starting from built-in defaults."""
    fmt = dict(BUILTIN_DEFAULTS)
    if overrides:
        fmt.update(overrides)
    return fmt


# Each sample is (title, sections, fmt_overrides, kwargs)
SAMPLES = [
    # ── 1. Grocery checklist — tests box checkboxes, spacing, footer ──────────
    (
        "Grocery List",
        [{"heading": "Produce", "items": [
            "[ ] Everything bagel seasoning",
            "[ ] Organic whole milk",
            "[ ] Sourdough bread",
            "[ ] Eggs (dozen)",
        ]}, {"heading": "Pantry", "items": [
            "[ ] Olive oil",
            "[ ] Garlic powder",
        ]}],
        {},
        {},
    ),

    # ── 2. Long-word wrap test — ensures nothing gets cut at paper edge ────────
    (
        "Wrap Test",
        [{"heading": None, "items": [
            "[ ] Everything bagel seasoning blend with sea salt",
            "This is a very long line intended to wrap across multiple visual "
            "lines to test indentation and avoid any clipping: HDMI extender "
            "on smart plug — to control heat?",
            "[ ] Supercalifragilisticexpialidocious (extra long single word)",
            "- Another dash bullet that is quite long and should wrap nicely "
            "with the correct indent on continuation lines",
        ]}],
        {},
        {},
    ),

    # ── 3. Short list — verifies it doesn't print an enormous blank receipt ────
    (
        "Quick Note",
        [{"heading": None, "items": [
            "[ ] Pick up dry cleaning",
            "[ ] Call dentist",
        ]}],
        {"min_page_height": 80},
        {},
    ),

    # ── 4. Mixed items — plain text, dashes, checkboxes ───────────────────────
    (
        "Mixed Items",
        [{"heading": "Tasks", "items": [
            "[ ] Checkbox item that might wrap to see proper indentation",
            "- Dash bullet with wrapping to confirm indent is preserved",
            "Plain paragraph line with no marker",
            "[ ] Final checkbox",
        ]}],
        {},
        {},
    ),

    # ── 5. Bracket-style checkboxes — verifies legacy style still works ────────
    (
        "Classic Style",
        [{"heading": None, "items": [
            "[ ] Milk",
            "[ ] Bread",
            "[ ] Cheese",
        ]}],
        {"checkbox_style": "bracket", "show_footer": False},
        {},
    ),

    # ── 6. Agenda / multi-section — tests section headings and dividers ────────
    (
        "Morning Agenda",
        [
            {"heading": "Weather", "items": ["Sunny, high 72°F"]},
            {"heading": "Tasks",   "items": [
                "[ ] Reply to emails",
                "[ ] Team standup at 10am",
                "[ ] Code review for PR #42",
            ]},
            {"heading": "Reminders", "items": [
                "- Water plants",
                "- Take vitamins",
            ]},
        ],
        {"show_footer": False},
        {},
    ),

    # ── 7. Centered note — tests text_align: center ───────────────────────────
    (
        "Daily Affirmation",
        [{"heading": None, "items": [
            "You are doing great.",
            "Keep going.",
            "",
            "One step at a time.",
        ]}],
        {"text_align": "center", "show_footer": False, "font_size": 12},
        {},
    ),
]


def main(open_files=False):
    out_paths = []
    for i, (title, sections, fmt_overrides, kwargs) in enumerate(SAMPLES, start=1):
        print(f"\nGenerating sample {i}: {title!r}")
        fmt  = _fmt(fmt_overrides)
        path = generate_pdf(title, sections, fmt, **kwargs)
        print(f"  → {path}")
        out_paths.append(path)
        if open_files and path:
            try:
                subprocess.run(["open", path], check=False)
            except Exception as e:
                print(f"  Failed to open PDF: {e}")

    print("\nAll generated files:")
    for p in out_paths:
        print(f"  {p}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="Open generated PDFs (macOS `open`)")
    args = parser.parse_args()
    main(open_files=args.open)
