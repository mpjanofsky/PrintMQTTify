import paho.mqtt.client as mqtt
import os
import subprocess
import time
import threading
import tempfile
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
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
        title = payload.get("title", "Print Job")
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
        # Page sizing and layout
        page_width = 80 * mm  # 80mm in points (thermal receipt width)
        margin = 5 * mm  # Margins for the receipt
        content_width = page_width - (2 * margin)

        # Fonts and sizes (tweakable)
        font_title = "Helvetica-Bold"
        font_title_size = 12
        font_body = "Helvetica"
        font_body_size = 10
        font_footer = "Helvetica-Oblique"
        font_footer_size = 8

        # Split message into logical lines and wrap to content width
        raw_lines = message.split('\n')
        line_height = max(font_body_size + 2, 12)  # spacing between lines in points

        # Helper: wrap a single logical line into multiple visual lines
        def wrap_line(text):
            if not text:
                return [""]
            words = text.split(' ')
            lines_out = []
            cur = words[0]
            for w in words[1:]:
                test = cur + ' ' + w
                if stringWidth(test, font_body, font_body_size) <= content_width:
                    cur = test
                else:
                    lines_out.append(cur)
                    cur = w
            lines_out.append(cur)
            return lines_out

        wrapped_lines = []
        for rl in raw_lines:
            wrapped_lines.extend(wrap_line(rl))

        # Calculate the required height for the content
        calculated_height = margin + (len(wrapped_lines) + 4) * line_height  # title + divider + footer

        # Ensure portrait orientation (height > width)
        page_height = max(calculated_height, page_width + 1)

        # Use a unique temporary file to avoid collisions
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf_path = tmp.name
        tmp.close()

        c = canvas.Canvas(pdf_path, pagesize=(page_width, page_height))

        # Start drawing from the top of the page
        y = page_height - margin

        # Title Section: center the title within content area
        c.setFont(font_title, font_title_size)
        title_width = stringWidth(title, font_title, font_title_size)
        title_x = margin + max(0, (content_width - title_width) / 2)
        c.drawString(title_x, y, title)

        # Divider
        y -= line_height
        c.line(margin, y, page_width - margin, y)

        # Message Section
        y -= line_height
        c.setFont(font_body, font_body_size)
        for line in wrapped_lines:
            c.drawString(margin, y, line)
            y -= line_height

        # Footer Section: timestamp and attribution
        footer_text = f"Generated by PrintMQTTify — {datetime.now().isoformat(timespec='seconds')}"
        c.setFont(font_footer, font_footer_size)
        c.drawString(margin, y - line_height, footer_text)

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
