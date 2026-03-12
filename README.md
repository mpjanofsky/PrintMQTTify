PrintMQTTify
============

A Docker-based bridge that turns MQTT messages into printed receipts via CUPS.
Send structured JSON from Home Assistant (or any MQTT client) and get a formatted
slip from your thermal receipt printer.

This fork adds named style presets, multi-section layouts, QR code support,
and a richer HA scripting experience — all while keeping the container-based setup
simple to deploy.

* * * * *

Features
--------

-   **CUPS Integration** — Fully functional CUPS server with persistent configuration.
-   **MQTT Print Jobs** — Listens for JSON payloads to process print jobs.
-   **Named Styles** — Choose from built-in style presets (`default`, `compact`, `receipt`,
    `minimal`, `agenda`, `note`) and override individual values per message.
-   **Multi-section Layouts** — Structure printouts with distinct labelled sections
    for daily agendas, scorecards, and more.
-   **QR Codes** — Embed QR codes (WiFi passwords, URLs, plain text) in any printout.
-   **Plain Text Mode** — Skip markdown parsing for simple ad-hoc messages.
-   **USB Printer Support** — Compatible with USB printers and custom drivers.
-   **Web Control Panel** — Optional web interface on port 8080.
-   **Home Automation Ready** — Designed for Home Assistant via MQTT.

* * * * *

Use Cases
---------

1.  **Daily Agenda** — Print weather, calendar, tasks, and an affirmation every morning.
2.  **Shopping Lists** — Print unchecked todo items with checkboxes.
3.  **WiFi Guest Slips** — Welcome guests with a QR code for your network.
4.  **Ad-hoc Notes** — Send a quick message from a dashboard button or voice command.
5.  **Food Labels** — Print made-on / use-by dates for meal prep containers.
6.  **Game Night Scoreboard** — Print scores on demand from HA input_number helpers.
7.  **Leaving-Home Checklists** — Trigger a checklist when everyone leaves the house.

See [HA Script Examples](docs/HA%20Script%20Examples.md) for complete copy-paste automations.

* * * * *

Prerequisites
-------------

1.  **Docker** — [Install Docker](https://docs.docker.com/get-docker/)
2.  **Git** — [Install Git](https://git-scm.com/)
3.  **MQTT Broker** — A working broker (e.g., Mosquitto). Note its IP, username, and password.
4.  **USB Printer** — Use `lsusb` and `dmesg | grep usb` to find the device path (e.g., `/dev/usb/lp0`).

* * * * *

Installation
------------

### 1. Clone the repository

```bash
git clone https://github.com/Aesgarth/PrintMQTTify.git
cd PrintMQTTify
```

### 2. Build the Docker image

```bash
docker build -t printmqttify .
```

### 3. Run the container

```bash
docker run --name printmqttify_container \
  -d \
  --privileged \
  -p 631:631 \
  -p 8080:8080 \
  --device=/dev/usb/lp0:/dev/usb/lp0 \
  --ulimit nofile=65536:65536 \
  -e MQTT_BROKER="<your-mqtt-broker-ip>" \
  -e MQTT_USERNAME="<your-mqtt-username>" \
  -e MQTT_PASSWORD="<your-mqtt-password>" \
  -e MQTT_TOPIC="printer/commands" \
  -e ADMIN_USER="admin" \
  -e ADMIN_PASS="adminpassword" \
  printmqttify
```

### Using Docker Compose

```yaml
version: '3.8'

services:
  printmqttify:
    image: printmqttify
    container_name: printmqttify_container
    privileged: true
    ports:
      - "631:631"
      - "8080:8080"
    devices:
      - "/dev/usb/lp0:/dev/usb/lp0"
    environment:
      - MQTT_BROKER=<your-mqtt-broker-ip>
      - MQTT_USERNAME=<your-mqtt-username>
      - MQTT_PASSWORD=<your-mqtt-password>
      - MQTT_TOPIC=printer/commands
      - ADMIN_USER=admin
      - ADMIN_PASS=adminpassword
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - cups_config:/etc/cups
    stdin_open: true
    tty: true

volumes:
  cups_config:
```

```bash
docker-compose up -d
```

* * * * *

Setup
-----

### 1. Add your printer in CUPS

1.  Open `https://<host-ip>:631` in a browser.
2.  Log in with the CUPS admin credentials (`ADMIN_USER` / `ADMIN_PASS`).
3.  Go to **Administration > Add Printer**, select your USB printer, choose the driver,
    and print a test page to confirm it works.

### 2. Note your printer name

The printer name used in `printer_name` must exactly match the name shown in CUPS
(case-sensitive, spaces replaced with underscores — e.g., `Epson_TM-m30`).

* * * * *

Payload Schema
--------------

Send JSON to the MQTT topic configured in `MQTT_TOPIC` (default: `printer/commands`).

```json
{
  "printer_name": "Epson_TM-m30",
  "title": "Optional title (defaults to current date/time)",
  "style": "default",
  "plain_text": false,
  "formatting": {
    "font_size": 10,
    "title_size": 14,
    "show_footer": true,
    "margin_top": 2,
    "margin_bottom": 2,
    "margin_sides": 4,
    "min_page_height": 80,
    "text_align": "left"
  },
  "sections": [
    {
      "heading": "Optional section heading",
      "items": [
        "Plain text item",
        "- Dash bullet item",
        "[ ] Checkbox item"
      ]
    }
  ],
  "qr_code": {
    "content": "https://example.com",
    "size": "medium",
    "caption": "Scan me"
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `printer_name` | **Yes** | CUPS printer name (case-sensitive) |
| `title` | No | Title printed at top; defaults to current date/time |
| `style` | No | Named style preset (see below); defaults to `default` |
| `plain_text` | No | `true` to skip checkbox/dash parsing; defaults to `false` |
| `formatting` | No | Per-message overrides for any style field |
| `sections` | No | Array of content sections with optional headings |
| `message` | No | Simple string alternative to `sections` (single block) |
| `qr_code` | No | QR code to embed; string or object (see below) |

### Named Styles

Defined in `configs/styles.yaml` — edit to add your own presets.

| Style | Font | Footer | Best for |
|-------|------|--------|----------|
| `default` | 10pt | Yes | General purpose |
| `compact` | 8pt | No | Short notes, labels |
| `receipt` | 11pt | Yes | Easy-to-read lists |
| `minimal` | 10pt | No | Quick ad-hoc slips |
| `agenda` | 9pt | No | Daily schedule |
| `note` | 12pt centred | No | Affirmations, short messages |

**Resolution order** (last wins): built-in defaults → named style → `formatting` overrides.

### Section Items Syntax

Within each section's `items` array:

| Prefix | Renders as |
|--------|-----------|
| `[ ]` or `[x]` | Checkbox (unchecked / checked) |
| `- ` | Dash bullet |
| *(plain text)* | Regular body text |
| `""` (empty) | Blank line |

### QR Code

```json
"qr_code": {
  "content": "WIFI:S:MyNetwork;T:WPA;P:mypassword;;",
  "size": "small|medium|large",
  "caption": "Scan to connect"
}
```

String shorthand (URL or plain text, default medium size):
```json
"qr_code": "https://example.com"
```

**WiFi QR format:** `WIFI:S:<SSID>;T:<WPA|WEP|nopass>;P:<password>;;`

* * * * *

Customising Styles
------------------

Edit `configs/styles.yaml` and rebuild the image to add or change named presets.
All fields shown in `default` are available in any style:

```yaml
styles:
  my_style:
    font_size: 9
    title_size: 12
    margin_top: 2
    margin_bottom: 2
    margin_sides: 4
    show_footer: false
    min_page_height: 60
    text_align: left
```

Then use `"style": "my_style"` in your MQTT payload.

* * * * *

Environment Variables
---------------------

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER` | `localhost` | MQTT broker IP or hostname |
| `MQTT_USERNAME` | *(none)* | MQTT username |
| `MQTT_PASSWORD` | *(none)* | MQTT password |
| `MQTT_TOPIC` | `printer/commands` | Topic to subscribe to |
| `ADMIN_USER` | `admin` | CUPS admin username |
| `ADMIN_PASS` | `adminpassword` | CUPS admin password |
| `TZ` | *(system)* | Timezone, e.g. `America/New_York` |

* * * * *

Verification
------------

Send a test message from the command line:

```bash
mosquitto_pub -h <broker-ip> -u <user> -P <pass> \
  -t printer/commands \
  -m '{"printer_name":"Epson_TM-m30","message":"Hello, World!"}'
```

Check container logs if nothing prints:

```bash
docker logs printmqttify_container
```

* * * * *

Troubleshooting
---------------

See [Troubleshooting Documentation](docs/troubleshooting.md).

* * * * *

Contributing
------------

Contributions are welcome. Submit issues or pull requests on GitHub.

* * * * *

License
-------

Creative Commons Zero v1.0 Universal (CC0 1.0). See the LICENSE file for details.
