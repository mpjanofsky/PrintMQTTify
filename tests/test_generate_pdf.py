import os
import sys
import unittest

# Ensure app/ is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app")))

from printer_mqtt_handler import generate_pdf


class GeneratePDFTests(unittest.TestCase):
    def test_generate_simple_pdf(self):
        path = generate_pdf("Unit Test", "Line1\nLine2")
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path), f"PDF not found at {path}")
        self.assertTrue(os.path.getsize(path) > 0, "Generated PDF is empty")
        try:
            os.remove(path)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
