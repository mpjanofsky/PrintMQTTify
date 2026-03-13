import paho.mqtt.client as mqtt
import os
import subprocess
import time
import threading
import tempfile
import re
import json
import yaml
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ─── MQTT configuration ───────────────────────────────────────────────────────
broker = os.getenv("MQTT_BROKER", "localhost")
username = os.getenv("MQTT_USERNAME")
password = os.getenv("MQTT_PASSWORD")
topic = os.getenv("MQTT_TOPIC", "printer/commands")
availability_topic = "printer/availability"

# ─── Font registration ────────────────────────────────────────────────────────
_DEJAVU_FONTS = {
    "DejaVuSans":             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSans-Bold":        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Oblique":     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "DejaVuSans-BoldOblique": "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
}
_NOTO_EMOJI_PATH = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
_FONTS_AVAILABLE = set()


def _register_fonts():
    """Register DejaVu Sans TTF fonts and NotoEmoji; gracefully skips any that are missing."""
    for name, path in _DEJAVU_FONTS.items():
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"not found: {path}")
            pdfmetrics.registerFont(TTFont(name, path))
            _FONTS_AVAILABLE.add(name)
        except Exception as e:
            print(f"Warning: could not register font '{name}': {e}")
    if _FONTS_AVAILABLE:
        print(f"Registered fonts: {', '.join(sorted(_FONTS_AVAILABLE))}")
    else:
        print("Warning: no DejaVu fonts registered; falling back to built-in Helvetica.")
    try:
        if not os.path.exists(_NOTO_EMOJI_PATH):
            raise FileNotFoundError(f"not found: {_NOTO_EMOJI_PATH}")
        pdfmetrics.registerFont(TTFont("NotoEmoji", _NOTO_EMOJI_PATH))
        _FONTS_AVAILABLE.add("NotoEmoji")
        print("Registered NotoEmoji font.")
    except Exception as e:
        print(f"Warning: could not register NotoEmoji (emoji will use body font): {e}")


_register_fonts()


def _is_emoji(ch):
    """Return True if *ch* is an emoji or symbol codepoint."""
    cp = ord(ch)
    return (
        0x2600 <= cp <= 0x27BF   # Misc Symbols and Dingbats
        or cp >= 0x1F300          # Emoji blocks (emoticons, symbols, transport, etc.)
    )


def _draw_text_run(c, x, y, text, font_main, font_size):
    """Draw *text* on canvas *c*, switching to NotoEmoji for emoji codepoints.

    Non-emoji characters use *font_main*. Restores *font_main* on the canvas
    before returning so subsequent draw calls are unaffected.
    Falls back to *font_main* for all characters if NotoEmoji is unavailable.
    """
    emoji_available = "NotoEmoji" in _FONTS_AVAILABLE
    cur_font = None
    cur_chunk = ""
    for ch in text:
        want = "NotoEmoji" if (emoji_available and _is_emoji(ch)) else font_main
        if want != cur_font:
            if cur_chunk:
                c.setFont(cur_font, font_size)
                c.drawString(x, y, cur_chunk)
                x += stringWidth(cur_chunk, cur_font, font_size)
            cur_chunk = ch
            cur_font = want
        else:
            cur_chunk += ch
    if cur_chunk:
        c.setFont(cur_font, font_size)
        c.drawString(x, y, cur_chunk)
    # Restore the expected font for subsequent canvas operations.
    c.setFont(font_main, font_size)


def _resolve_fonts(font_family):
    """Return (body, heading, title, footer) font names for the requested family.

    Falls back to Helvetica if the requested TTF fonts were not registered.
    """
    if font_family == "dejavu" and "DejaVuSans" in _FONTS_AVAILABLE:
        return (
            "DejaVuSans",
            "DejaVuSans-Bold",
            "DejaVuSans-Bold",
            "DejaVuSans-Oblique",
        )
    return ("Helvetica", "Helvetica-Bold", "Helvetica-Bold", "Helvetica-Oblique")


# ─── Formatting defaults ──────────────────────────────────────────────────────
# All values are overridable via a named style or per-message "formatting" dict.
BUILTIN_DEFAULTS = {
    "font_size": 9,             # body text in points
    "title_size": 14,           # title text in points (auto-scales down if needed)
    "margin_top": 2,            # mm
    "margin_bottom": 2,         # mm
    "margin_sides": 2,          # mm
    "show_footer": True,
    "min_page_height": 80,      # mm (prevents excessively short receipts)
    "text_align": "left",       # "left" or "center" for plain body items
    "font_family": "dejavu",    # "dejavu" or "helvetica"
    "checkbox_style": "box",    # "box" (drawn square) or "bracket" ([  ])
}


def _load_styles():
    """Load named style presets from styles.yaml, falling back to empty dict."""
    candidate_paths = [
        "/app/configs/styles.yaml",
        os.path.join(os.path.dirname(__file__), "..", "configs", "styles.yaml"),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return yaml.safe_load(f).get("styles", {})
            except Exception as e:
                print(f"Warning: could not load styles from {path}: {e}")
    print("Warning: styles.yaml not found; using built-in defaults only.")
    return {}


STYLES = _load_styles()


def resolve_formatting(payload):
    """Merge built-in defaults → named style → per-message overrides."""
    result = dict(BUILTIN_DEFAULTS)
    style_name = payload.get("style", "default")
    if style_name in STYLES:
        result.update(STYLES[style_name])
    elif style_name != "default":
        print(f"Warning: unknown style '{style_name}'; falling back to defaults.")
    if "formatting" in payload:
        result.update(payload["formatting"])
    return result


def normalize_sections(payload):
    """Convert payload content into a list of section dicts.

    If a 'sections' array is present it is returned as-is.
    A bare 'message' string is wrapped in a single unnamed section.
    """
    if "sections" in payload:
        return payload["sections"]
    message = payload.get("message", "No message provided")
    return [{"heading": None, "items": message.splitlines()}]


# ─── PDF rendering helpers ────────────────────────────────────────────────────

def _wrap_to_width(text, max_width, font_name, font_size):
    """Word-wrap *text* to fit within *max_width* points.

    Words that are individually wider than *max_width* are broken at the
    character level so nothing overflows the page edge.
    """
    if not text:
        return [""]

    def _break_word(word):
        """Split a single oversized word character by character."""
        pieces, cur = [], ""
        for ch in word:
            test = cur + ch
            if stringWidth(test, font_name, font_size) <= max_width:
                cur = test
            else:
                if cur:
                    pieces.append(cur)
                cur = ch
        if cur:
            pieces.append(cur)
        return pieces or [word]

    lines_out = []
    cur = ""
    for word in text.split(" "):
        # Handle words that are too wide on their own
        if stringWidth(word, font_name, font_size) > max_width:
            if cur:
                lines_out.append(cur)
                cur = ""
            pieces = _break_word(word)
            lines_out.extend(pieces[:-1])
            cur = pieces[-1]
            continue

        test = (cur + " " + word).strip()
        if not cur or stringWidth(test, font_name, font_size) <= max_width:
            cur = test
        else:
            lines_out.append(cur)
            cur = word

    if cur:
        lines_out.append(cur)
    return lines_out or [""]


def _process_item(text, content_width, font_body, font_size,
                  checkbox_marker, checkbox_marker_width, plain_text):
    """Parse one item string into render tuples.

    Each tuple is (chunk, indent_pts, draw_marker, marker_type, is_first_line) where:
      chunk              - text to draw
      indent_pts         - left indent in points (0 = no indent)
      draw_marker        - whether to draw the bullet/checkbox on this line
      marker_type        - 'checkbox', 'dash', or None
      is_first_line      - True only for the first render line of each original item
                           (used to insert inter-item spacing in the render loop)
    """
    if not text:
        return [("", 0, False, None, True)]

    # Right-side safety buffer (points) — prevents text reaching the paper edge.
    # Thermal printers have a mechanical margin inside the 80 mm paper width;
    # 6 pt (~2 mm) keeps text clear of the physical print boundary.
    _RIGHT_BUFFER = 6

    # Multi-line items: split on \n, render main line normally, sub-lines with
    # a fixed point-based indent so they align correctly in proportional fonts.
    if '\n' in text:
        parts = text.split('\n')
        main_tuples = _process_item(
            parts[0], content_width, font_body, font_size,
            checkbox_marker, checkbox_marker_width, plain_text,
        )
        sub_indent = font_size * 2.8
        sub_tuples = []
        for sub in parts[1:]:
            sub_chunks = _wrap_to_width(
                sub.strip(),
                content_width - sub_indent - _RIGHT_BUFFER,
                font_body, font_size,
            )
            sub_tuples.extend(
                [(ch, sub_indent, False, None, False) for ch in sub_chunks]
            )
        return main_tuples + sub_tuples

    # Leading-space indentation — detect BEFORE plain_text branch so it applies
    # in both normal and plain-text modes.
    leading = len(text) - len(text.lstrip(' '))
    if leading > 0:
        space_width = stringWidth(text[:leading], font_body, font_size)
        content = text[leading:]
        chunks = _wrap_to_width(
            content,
            content_width - space_width - _RIGHT_BUFFER,
            font_body, font_size,
        )
        return [(ch, space_width, False, None, i == 0) for i, ch in enumerate(chunks)]

    if plain_text:
        chunks = _wrap_to_width(text, content_width - _RIGHT_BUFFER, font_body, font_size)
        return [(ch, 0, False, None, i == 0) for i, ch in enumerate(chunks)]

    m = re.match(r'^(?:-\s+)?(\[[ xX]?\])\s+(.*)$', text)
    if m:
        content = m.group(2)
        chunks = _wrap_to_width(
            content,
            content_width - checkbox_marker_width - _RIGHT_BUFFER,
            font_body, font_size,
        )
        return [(ch, checkbox_marker_width, i == 0, 'checkbox', i == 0) for i, ch in enumerate(chunks)]

    if text.startswith("- "):
        content = text[2:]
        dash_width = stringWidth("- ", font_body, font_size)
        chunks = _wrap_to_width(
            content,
            content_width - dash_width - _RIGHT_BUFFER,
            font_body, font_size,
        )
        return [(ch, dash_width, i == 0, 'dash', i == 0) for i, ch in enumerate(chunks)]

    chunks = _wrap_to_width(text, content_width - _RIGHT_BUFFER, font_body, font_size)
    return [(ch, 0, False, None, i == 0) for i, ch in enumerate(chunks)]


def _render_logo_block(c, logo, margin_sides, y, content_width):
    """Render a logo/image. Returns the updated y position (moved downward).

    *logo* can be a plain file path string, or a dict with keys:
      path      - local file path (e.g. /app/logo.png)
      url       - remote URL (downloaded to a temp file)
      width_mm  - desired width in mm (default 30; height preserves aspect ratio)
      align     - "left", "center" (default), or "right"
    """
    try:
        from urllib.request import urlretrieve
        from PIL import Image

        if isinstance(logo, str):
            path, url, width_mm, align = logo, None, 30, "center"
        else:
            path     = logo.get("path")
            url      = logo.get("url")
            width_mm = logo.get("width_mm", 30)
            align    = logo.get("align", "center")

        # Download remote image if no local path provided
        if not path and url:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.close()
            urlretrieve(url, tmp.name)
            path = tmp.name

        if not path or not os.path.exists(path):
            print(f"Warning: logo path not found: {path!r}")
            return y

        with Image.open(path) as img:
            orig_w, orig_h = img.size

        width_pts  = width_mm * mm
        height_pts = width_pts * orig_h / orig_w  # preserve aspect ratio

        if align == "center":
            x = margin_sides + max(0, (content_width - width_pts) / 2)
        elif align == "right":
            x = margin_sides + content_width - width_pts
        else:
            x = margin_sides

        c.drawImage(path, x, y - height_pts, width_pts, height_pts,
                    preserveAspectRatio=True, mask="auto")
        return y - height_pts

    except Exception as e:
        print(f"Error rendering logo: {e}")
        return y


def _render_qr_block(c, qr_code, margin, y, content_width, line_height):
    """Render a QR code image with optional caption. Returns updated y."""
    try:
        import qrcode as qrcode_lib

        if isinstance(qr_code, str):
            content = qr_code
            caption = None
            qr_size_mm = 50
        else:
            content = qr_code.get("content", "")
            caption = qr_code.get("caption")
            size_map = {"small": 30, "medium": 50, "large": 70}
            qr_size_mm = size_map.get(qr_code.get("size", "medium"), 50)

        qr = qrcode_lib.QRCode(box_size=4, border=2)
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        img_path = "/tmp/qr_code.png"
        img.save(img_path)

        qr_pts = qr_size_mm * mm
        x_offset = (content_width - qr_pts) / 2

        y -= line_height / 2
        c.drawImage(img_path, margin + x_offset, y - qr_pts, qr_pts, qr_pts)
        y -= qr_pts

        if caption:
            c.setFont("Helvetica", 8)
            caption_w = stringWidth(caption, "Helvetica", 8)
            caption_x = margin + (content_width - caption_w) / 2
            y -= line_height / 2
            c.drawString(caption_x, y, caption)
            y -= line_height

        return y

    except ImportError:
        print("Warning: qrcode library not available; skipping QR code.")
        return y
    except Exception as e:
        print(f"Error rendering QR code: {e}")
        return y


# ─── Core PDF generation ──────────────────────────────────────────────────────

def generate_pdf(title, sections, fmt, plain_text=False, qr_code=None, logo=None, subtitle=None):
    """Generate a receipt-width PDF and return its temp file path."""
    try:
        page_width    = 80 * mm
        margin_top    = fmt["margin_top"] * mm
        margin_bottom = fmt["margin_bottom"] * mm
        margin_sides  = fmt["margin_sides"] * mm
        content_width = page_width - 2 * margin_sides

        # ── Font selection ─────────────────────────────────────────────────────
        font_family = fmt.get("font_family", "dejavu")
        font_body, font_heading, font_title, font_footer = _resolve_fonts(font_family)
        font_title_size  = fmt["title_size"]
        font_body_size   = fmt["font_size"]
        font_footer_size = 8

        # ── Checkbox configuration ─────────────────────────────────────────────
        checkbox_style = fmt.get("checkbox_style", "box")

        if checkbox_style == "box":
            # Box height ≈ cap-height of the font (~72 % of em); bottom sits on baseline.
            box_size              = font_body_size * 0.72
            checkbox_gap          = 5   # pts gap between drawn box and text
            checkbox_marker       = None  # drawn via c.rect(), not text
            checkbox_marker_width = box_size + checkbox_gap
        else:  # "bracket"
            box_size              = 0
            checkbox_gap          = 8   # bracket needs more visual breathing room
            checkbox_marker       = "[  ]"
            checkbox_marker_width = (
                stringWidth(checkbox_marker, font_body, font_body_size) + checkbox_gap
            )

        line_height = max(font_body_size + 4, 13)

        # ── Estimate logo height for page sizing ───────────────────────────────
        logo_height_pts = 0
        if logo:
            try:
                from PIL import Image
                p = (logo.get("path") or logo.get("url")) if isinstance(logo, dict) else logo
                if p and os.path.exists(str(p)):
                    w_mm = logo.get("width_mm", 30) if isinstance(logo, dict) else 30
                    with Image.open(str(p)) as img:
                        ow, oh = img.size
                    w_pts = w_mm * mm
                    logo_height_pts = w_pts * oh / ow + line_height  # image + gap below
            except Exception:
                logo_height_pts = 30 * mm  # conservative fallback estimate

        # ── Pre-process sections into render tuples ────────────────────────────
        rendered_sections = []
        for section in sections:
            heading      = section.get("heading")
            items        = section.get("items", [])
            render_lines = []
            for item in items:
                render_lines.extend(_process_item(
                    item, content_width, font_body, font_body_size,
                    checkbox_marker, checkbox_marker_width, plain_text,
                ))
            rendered_sections.append({"heading": heading, "render_lines": render_lines})

        # ── Estimate QR code height for page sizing ────────────────────────────
        qr_height = 0
        if qr_code:
            if isinstance(qr_code, dict):
                size_map   = {"small": 30, "medium": 50, "large": 70}
                qr_size_mm = size_map.get(qr_code.get("size", "medium"), 50)
                has_caption = bool(qr_code.get("caption"))
            else:
                qr_size_mm  = 50
                has_caption = False
            qr_height = (
                qr_size_mm * mm
                + (line_height if has_caption else 0)
                + 2 * line_height
            )

        # ── Calculate page height ──────────────────────────────────────────────
        total_lines = 0
        for sec in rendered_sections:
            if sec["heading"]:
                total_lines += 2   # heading text + divider gap
            item_count   = sum(1 for tup in sec["render_lines"] if tup[4])
            total_lines += len(sec["render_lines"])
            if item_count > 1:
                total_lines += (item_count - 1) * 0.5   # inter-item gaps
            total_lines += 1       # inter-section gap

        subtitle_height_pts = 0
        if subtitle:
            subtitle_size_est = max(fmt["title_size"] - 3, 8)
            sub_ascent_est = (pdfmetrics.getAscent(font_body) * subtitle_size_est) / 1000.0
            subtitle_height_pts = sub_ascent_est + 2 + line_height * 0.3

        title_ascent = (pdfmetrics.getAscent(font_title) * font_title_size) / 1000.0
        calculated_height = (
            margin_top
            + logo_height_pts
            + title_ascent
            + subtitle_height_pts
            + (total_lines + 4.5) * line_height   # 4.5 covers title area + extra divider gap
            + (font_footer_size if fmt["show_footer"] else 0)
            + qr_height
            + margin_bottom
        )

        min_height  = fmt["min_page_height"] * mm
        page_height = max(calculated_height, min_height)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf_path = tmp.name
        tmp.close()

        c = canvas.Canvas(pdf_path, pagesize=(page_width, page_height))

        # ── Logo (above title) ─────────────────────────────────────────────────
        y = page_height - margin_top
        if logo:
            y = _render_logo_block(c, logo, margin_sides, y, content_width)
            y -= line_height / 2   # small gap between logo and title

        # ── Title (auto-scales down if too wide) ───────────────────────────────
        while True:
            if (stringWidth(title, font_title, font_title_size) <= content_width
                    or font_title_size <= 8):
                break
            font_title_size -= 1

        c.setFont(font_title, font_title_size)
        title_ascent_actual = (pdfmetrics.getAscent(font_title) * font_title_size) / 1000.0
        title_width = stringWidth(title, font_title, font_title_size)
        title_x     = margin_sides + max(0, (content_width - title_width) / 2)

        y -= title_ascent_actual
        _draw_text_run(c, title_x, y, title, font_title, font_title_size)

        # ── Divider below title ────────────────────────────────────────────────
        y -= line_height
        c.setLineWidth(0.5)
        c.line(margin_sides, y, page_width - margin_sides, y)

        if subtitle:
            subtitle_size = max(font_title_size - 3, 8)
            subtitle_ascent = (pdfmetrics.getAscent(font_body) * subtitle_size) / 1000.0
            c.setFont(font_body, subtitle_size)
            subtitle_width = stringWidth(subtitle, font_body, subtitle_size)
            subtitle_x = margin_sides + max(0, (content_width - subtitle_width) / 2)
            y -= subtitle_ascent + 2   # tight clearance below divider line
            _draw_text_run(c, subtitle_x, y, subtitle, font_body, subtitle_size)
            y -= line_height * 0.3     # small spacer before first section
        else:
            y -= line_height
            y -= line_height * 0.5     # extra breathing room after divider

        # ── Render sections ────────────────────────────────────────────────────
        text_align = fmt.get("text_align", "left")
        for sec in rendered_sections:
            if sec["heading"]:
                c.setFont(font_heading, font_body_size)
                _draw_text_run(c, margin_sides, y, sec["heading"], font_heading, font_body_size)
                y -= 2
                c.setLineWidth(0.3)
                c.line(margin_sides, y, page_width - margin_sides, y)
                y -= line_height
                c.setFont(font_body, font_body_size)

            is_first_in_section = True
            for (chunk, indent_pts, draw_marker, marker_type, is_first_line) in sec["render_lines"]:
                # Add a gap between distinct items (not between wrapped continuation lines).
                if is_first_line and not is_first_in_section:
                    y -= line_height * 0.5
                is_first_in_section = False

                x = margin_sides
                if indent_pts > 0 and draw_marker:
                    if marker_type == 'checkbox':
                        if checkbox_style == "box":
                            # Centre the box on the x-height midpoint (~0.26 × em above baseline)
                            # so it aligns with mixed-case text rather than floating at cap-height.
                            box_y = y - font_body_size * 0.1
                            c.setLineWidth(0.8)
                            c.rect(x, box_y, box_size, box_size, stroke=1, fill=0)
                            c.setLineWidth(0.5)
                        else:
                            c.drawString(x, y, checkbox_marker)
                    else:
                        c.drawString(x, y, '-')
                    x = margin_sides + indent_pts
                elif indent_pts > 0:
                    x = margin_sides + indent_pts
                elif text_align == "center":
                    text_w = stringWidth(chunk, font_body, font_body_size)
                    x = margin_sides + max(0, (content_width - text_w) / 2)
                _draw_text_run(c, x, y, chunk, font_body, font_body_size)
                y -= line_height

            y -= int(line_height / 2)  # gap between sections

        # ── QR code block ──────────────────────────────────────────────────────
        if qr_code:
            y = _render_qr_block(c, qr_code, margin_sides, y, content_width, line_height)

        # ── Footer ─────────────────────────────────────────────────────────────
        if fmt["show_footer"]:
            formatted_time = datetime.now().strftime('%m/%d/%Y %I:%M %p')
            footer_text    = f"Printed at {formatted_time}"
            c.setFont(font_footer, font_footer_size)
            footer_min_y = margin_bottom + font_footer_size
            footer_y     = max(footer_min_y, y - line_height)
            c.drawString(margin_sides, footer_y, footer_text)

        c.save()
        print(f"PDF saved to {pdf_path}")
        return pdf_path

    except Exception as e:
        print(f"Error generating PDF: {e}")
        return None


# ─── Printer communication ────────────────────────────────────────────────────

def send_to_printer(printer_name, pdf_path):
    """Send the generated PDF to the named CUPS printer."""
    try:
        if not pdf_path:
            print("No PDF path provided to send_to_printer")
            return
        result = subprocess.run(
            ["lp", "-d", printer_name, pdf_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
        print(f"Printed successfully: {result.stdout}")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
        print(f"Failed to print. Error: {err}")


# ─── MQTT callbacks ───────────────────────────────────────────────────────────

def publish_availability(client, interval=60):
    """Publish printer availability status periodically."""
    def publish_status():
        while True:
            try:
                result = subprocess.run(
                    ["lpstat", "-p"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                status = "online" if "idle" in result.stdout else "offline"
            except Exception as e:
                print(f"Error checking printer status: {e}")
                status = "offline"
            print(f"Publishing status: {status}")
            client.publish(availability_topic, str(status), qos=1, retain=True)
            time.sleep(interval)

    threading.Thread(target=publish_status, daemon=True).start()


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker!")
        client.subscribe(topic)
        publish_availability(client)
    else:
        print(f"Failed to connect, return code {rc}")


def on_message(client, userdata, msg):
    print(f"Received message on {msg.topic}: {msg.payload.decode()}")
    try:
        data = json.loads(msg.payload.decode())
        printer_name = data.get("printer_name")
        if not printer_name:
            raise ValueError("Missing 'printer_name' in payload")

        title      = data.get("title") or datetime.now().strftime('%m/%d/%Y %I:%M %p')
        subtitle   = data.get("subtitle")
        fmt        = resolve_formatting(data)
        sections   = normalize_sections(data)
        plain_text = data.get("plain_text", False)
        qr_code    = data.get("qr_code")
        logo       = data.get("logo")

        pdf_path = generate_pdf(title, sections, fmt, plain_text, qr_code, logo, subtitle)
        if pdf_path:
            send_to_printer(printer_name, pdf_path)
        else:
            print("PDF generation failed; skipping print job")

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
    except Exception as e:
        print(f"Error handling message: {e}")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client = mqtt.Client(protocol=mqtt.MQTTv311)
    if username and password:
        client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(broker, 1883, 60)
        client.loop_forever()
    except Exception as e:
        print(f"Failed to start MQTT handler: {e}")
