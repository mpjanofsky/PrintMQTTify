import os
import sys
import unittest

# Ensure app/ is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app")))

from printer_mqtt_handler import (
    generate_pdf,
    resolve_formatting,
    normalize_sections,
    BUILTIN_DEFAULTS,
    STYLES,
)


def _pdf(title, sections=None, fmt=None, plain_text=False, qr_code=None):
    """Helper: generate a PDF and return its path."""
    if sections is None:
        sections = [{"heading": None, "items": ["Test item"]}]
    if fmt is None:
        fmt = dict(BUILTIN_DEFAULTS)
    return generate_pdf(title, sections, fmt, plain_text, qr_code)


def _cleanup(path):
    try:
        if path:
            os.remove(path)
    except Exception:
        pass


class TestResolveFomatting(unittest.TestCase):
    def test_default_style_matches_builtins(self):
        fmt = resolve_formatting({})
        self.assertEqual(fmt["font_size"], BUILTIN_DEFAULTS["font_size"])
        self.assertTrue(fmt["show_footer"])

    def test_named_style_compact(self):
        fmt = resolve_formatting({"style": "compact"})
        if STYLES:  # only assertable when styles.yaml is present
            self.assertFalse(fmt["show_footer"])
            self.assertLess(fmt["font_size"], BUILTIN_DEFAULTS["font_size"])

    def test_per_message_override(self):
        fmt = resolve_formatting({"formatting": {"font_size": 7, "show_footer": False}})
        self.assertEqual(fmt["font_size"], 7)
        self.assertFalse(fmt["show_footer"])

    def test_override_wins_over_named_style(self):
        fmt = resolve_formatting({"style": "receipt", "formatting": {"font_size": 6}})
        self.assertEqual(fmt["font_size"], 6)

    def test_unknown_style_falls_back_to_defaults(self):
        fmt = resolve_formatting({"style": "nonexistent_xyz"})
        self.assertEqual(fmt["font_size"], BUILTIN_DEFAULTS["font_size"])


class TestNormalizeSections(unittest.TestCase):
    def test_sections_passthrough(self):
        payload = {"sections": [{"heading": "A", "items": ["x"]}]}
        result = normalize_sections(payload)
        self.assertEqual(result, payload["sections"])

    def test_message_becomes_single_section(self):
        payload = {"message": "Line1\nLine2"}
        result = normalize_sections(payload)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["heading"])
        self.assertEqual(result[0]["items"], ["Line1", "Line2"])

    def test_no_content_defaults_to_placeholder(self):
        result = normalize_sections({})
        self.assertEqual(len(result), 1)
        self.assertIn("No message", result[0]["items"][0])


class TestGeneratePDF(unittest.TestCase):
    def test_simple_message(self):
        path = _pdf("Simple Test", [{"heading": None, "items": ["Hello, world!"]}])
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 0)
        _cleanup(path)

    def test_sections_with_headings(self):
        sections = [
            {"heading": "Calendar", "items": ["9:00 AM  Stand-up"]},
            {"heading": "Tasks", "items": ["[ ] Buy groceries", "[ ] Call mom"]},
        ]
        path = _pdf("Tuesday, March 10", sections)
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_checkbox_items(self):
        sections = [{"heading": None, "items": [
            "[ ] Apples",
            "[ ] Bread",
            "[x] Already done",
        ]}]
        path = _pdf("Shopping", sections)
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_dash_list(self):
        sections = [{"heading": None, "items": ["- Item one", "- Item two"]}]
        path = _pdf("Dash List", sections)
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_plain_text_mode_skips_markdown(self):
        # Checkbox syntax should NOT be parsed when plain_text=True
        sections = [{"heading": None, "items": ["[ ] This should render as raw text"]}]
        path = _pdf("Plain Test", sections, plain_text=True)
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_footer_hidden(self):
        fmt = {**BUILTIN_DEFAULTS, "show_footer": False}
        path = _pdf("No Footer", fmt=fmt)
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_compact_style(self):
        fmt = resolve_formatting({"style": "compact"})
        path = _pdf("Compact", fmt=fmt)
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_note_style_center_aligned(self):
        fmt = resolve_formatting({"style": "note"})
        sections = [{"heading": None, "items": ["\"You're doing great!\""]}]
        path = _pdf("Daily Note", sections, fmt=fmt)
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_empty_sections_list(self):
        path = _pdf("Empty", sections=[])
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_long_title_auto_scales(self):
        path = _pdf("This Is A Very Long Title That Should Scale Down Automatically")
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_qr_code_string_shorthand(self):
        try:
            import qrcode  # noqa: F401
        except ImportError:
            self.skipTest("qrcode library not installed")
        path = _pdf("QR Test", qr_code="https://example.com")
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_qr_code_dict_with_caption(self):
        try:
            import qrcode  # noqa: F401
        except ImportError:
            self.skipTest("qrcode library not installed")
        path = _pdf("WiFi", qr_code={
            "content": "WIFI:S:TestNet;T:WPA;P:secret;;",
            "caption": "Scan to connect",
            "size": "medium",
        })
        self.assertIsNotNone(path)
        _cleanup(path)

    def test_composite_daily_print(self):
        """Simulate a full daily agenda with weather, tasks, and affirmation."""
        sections = [
            {"heading": "Good Morning", "items": ["Today's high: 68°F"]},
            {"heading": "Calendar", "items": [
                "9:00 AM  Stand-up",
                "1:00 PM  Dentist",
            ]},
            {"heading": "Tasks", "items": [
                "[ ] Buy groceries",
                "[ ] Water the plants",
            ]},
            {"heading": None, "items": ["\"Small steps every day.\""]},
        ]
        fmt = resolve_formatting({"style": "agenda"})
        path = _pdf("Tuesday, March 10", sections, fmt=fmt)
        self.assertIsNotNone(path)
        _cleanup(path)


if __name__ == "__main__":
    unittest.main()
