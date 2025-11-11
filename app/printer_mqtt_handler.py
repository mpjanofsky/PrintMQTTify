import paho.mqtt.client as mqtt
import os
import subprocess
import time
import threading
import tempfile
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase import pdfmetrics
import re
import json

# Read broker, username, and password from environment variables
broker = os.getenv("MQTT_BROKER", "localhost")
username = os.getenv("MQTT_USERNAME")
password = os.getenv("MQTT_PASSWORD")
topic = os.getenv("MQTT_TOPIC", "printer/commands")
availability_topic = "printer/availability"


def publish_availability(client, interval=60):
    """Publish printer availability periodically."""
    def publish_status():
        while True:
            try:
                # Check if the printer is available
                result = subprocess.run(["lpstat", "-p"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                status = "online" if "idle" in result.stdout else "offline"
            except Exception as e:
                print(f"Error checking printer status: {e}")
                status = "offline"

            # Debug log and publish the status
            print(f"Publishing status: {status}")
            client.publish(availability_topic, str(status), qos=1, retain=True)
            time.sleep(interval)

    thread = threading.Thread(target=publish_status, daemon=True)
    thread.start()


def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the MQTT broker."""
    if rc == 0:
        print("Connected to MQTT broker!")
        client.subscribe(topic)
        # Start publishing availability
        publish_availability(client)
    else:
        print(f"Failed to connect, return code {rc}")



def on_message(client, userdata, msg):
    """Callback for when a message is received."""
    print(f"Received message: {msg.payload.decode()} on topic {msg.topic}")
    try:
        payload = json.loads(msg.payload.decode())
        print(f"Parsed payload: {payload}")
        printer_name = payload.get("printer_name")
        # Use provided title, or default to current date/time if not specified
        title = payload.get("title")
        if not title:
            title = datetime.now().strftime('%m/%d/%Y %I:%M %p')
        message = payload.get("message", "No message provided")

        if not printer_name:
            raise ValueError("Missing 'printer_name' in payload")

        # Generate a formatted PDF
        pdf_path = generate_pdf(title, message)

        # Send the PDF to the printer (only if generation succeeded)
        if pdf_path:
            send_to_printer(printer_name, pdf_path)
        else:
            print("PDF generation failed; skipping print job")

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
    except Exception as e:
        print(f"Error handling message: {e}")


def generate_pdf(title, message):
    """Generate a PDF optimized for thermal receipt printers."""
    try:
        # Fixed page width; height is dynamic
        page_width = 80 * mm  # 80mm in points (thermal receipt width)
        top_margin = 2 * mm
        bottom_margin = 2 * mm
        margin = 4 * mm
        content_width = page_width - (2 * margin)

        # Fonts and sizes
        font_title = "Helvetica-Bold"
        font_title_size = 14
        font_body = "Helvetica"
        font_body_size = 10
        font_footer = "Helvetica-Oblique"
        font_footer_size = 8

        checkbox_marker = "[  ]"
        checkbox_gap = 1

        raw_lines = message.split('\n')
        line_height = max(font_body_size + 2, 12)

        def wrap_to_width(text, max_width, font_name, font_size):
            if not text:
                return [""]
            words = text.split(' ')
            lines_out = []
            cur = words[0]
            for w in words[1:]:
                test = cur + ' ' + w
                if stringWidth(test, font_name, font_size) <= max_width:
                    cur = test
                else:
                    lines_out.append(cur)
                    cur = w
            lines_out.append(cur)
            return lines_out

        wrapped_lines = []
        for rl in raw_lines:
            m = re.match(r'^(?:-\s+)?(\[[ xX]?\])\s+(.*)$', rl)
            if m:
                content = m.group(2)
                marker_text = 'checkbox'
                marker_width = stringWidth(checkbox_marker, font_body, font_body_size) + checkbox_gap
                chunks = wrap_to_width(content, content_width - marker_width - 2, font_body, font_body_size)
                for i, ch in enumerate(chunks):
                    if i == 0:
                        wrapped_lines.append((ch, marker_width, True, marker_text))
                    else:
                        wrapped_lines.append((ch, marker_width, False, marker_text))
            elif rl.startswith('- '):
                content = rl[2:]
                dash_width = stringWidth('- ', font_body, font_body_size)
                chunks = wrap_to_width(content, content_width - dash_width - 2, font_body, font_body_size)
                for i, ch in enumerate(chunks):
                    if i == 0:
                        wrapped_lines.append((ch, dash_width, True, 'dash'))
                    else:
                        wrapped_lines.append((ch, dash_width, False, 'dash'))
            else:
                chunks = wrap_to_width(rl, content_width - 2, font_body, font_body_size)
                for ch in chunks:
                    wrapped_lines.append((ch, 0, False, None))

        # Compute title ascent early so we can reserve enough vertical space
        # when calculating the page height (prevents footer/content overlap).
        title_ascent = (pdfmetrics.getAscent(font_title) * font_title_size) / 1000.0

        # Calculate height conservatively: reserve room for title ascent, a
        # divider line, the message lines, a spacer before the footer, the
        # footer font height, and bottom margin.
        calculated_height = (
            top_margin
            + title_ascent
            + (len(wrapped_lines) + 4) * line_height
            + font_footer_size
            + bottom_margin
        )

        # Use a small minimum page height to avoid producing a square 80x80mm page
        # when content is very short. 30mm is a reasonable minimum receipt height
        # that keeps portrait orientation without large blank areas.
        min_height = 30 * mm
        page_height = max(calculated_height, min_height)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf_path = tmp.name
        tmp.close()

        c = canvas.Canvas(pdf_path, pagesize=(page_width, page_height))

        # Auto-scale title to fit
        while True:
            title_width = stringWidth(title, font_title, font_title_size)
            if title_width <= content_width or font_title_size <= 8:
                break
            font_title_size -= 1

        c.setFont(font_title, font_title_size)
        title_width = stringWidth(title, font_title, font_title_size)
        title_x = margin + max(0, (content_width - title_width) / 2)

    # Position the title baseline so the glyphs fit within the top margin.
        y = page_height - top_margin - title_ascent
        c.drawString(title_x, y, title)

        # Divider
        y -= line_height
        c.setLineWidth(0.5)
        c.line(margin, y, page_width - margin, y)

        # Message
        y -= line_height
        c.setFont(font_body, font_body_size)
        for (chunk, indent_pts, draw_dash, marker_text) in wrapped_lines:
            if indent_pts > 0 and draw_dash:
                if marker_text == 'checkbox':
                    c.drawString(margin, y, checkbox_marker)
                else:
                    c.drawString(margin, y, '-')
                indent_x = margin + indent_pts
                c.drawString(indent_x, y, chunk)
            elif indent_pts > 0 and not draw_dash:
                indent_x = margin + indent_pts
                c.drawString(indent_x, y, chunk)
            else:
                c.drawString(margin, y, chunk)
            y -= line_height

        # Footer
        now = datetime.now()
        formatted_time = now.strftime('%m/%d/%Y %I:%M %p')
        footer_text = f"Generated by PrintMQTTify — {formatted_time}"
        c.setFont(font_footer, font_footer_size)
        # Compute footer baseline: ensure it's at least `bottom_margin` above page bottom
        footer_min_y = bottom_margin + (font_footer_size)
        # normally footer sits one line below last content: y - line_height
        footer_y = max(footer_min_y, y - line_height)
        c.drawString(margin, footer_y, footer_text)

        c.save()
        print(f"PDF saved to {pdf_path}")
        return pdf_path
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return None


def send_to_printer(printer_name, pdf_path):
    """Send the generated PDF to the printer."""
    try:
        if not pdf_path:
            print("No PDF path provided to send_to_printer")
            return

        result = subprocess.run(
            ["lp", "-d", printer_name, pdf_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        print(f"Printed successfully: {result.stdout}")
    except subprocess.CalledProcessError as e:
        # e.stderr may already be a string when text=True
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
        print(f"Failed to print. Error: {err}")


if __name__ == "__main__":
    # Create an MQTT client instance
    client = mqtt.Client(protocol=mqtt.MQTTv311)

    # Set username and password if provided
    if username and password:
        client.username_pw_set(username, password)

    # Assign callback functions
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect to the broker
    try:
        client.connect(broker, 1883, 60)
        # Start the MQTT loop
        client.loop_forever()
    except Exception as e:
        print(f"Failed to start MQTT handler: {e}")
