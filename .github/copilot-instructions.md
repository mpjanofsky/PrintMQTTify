## Purpose
This file gives concise, actionable guidance for an AI coding agent to be productive in the PrintMQTTify repository. Focus on the minimal, discoverable patterns developers rely on: the architecture, environment configuration, integration points, and a few concrete examples.

## Big-picture architecture
-  Two primary runtime components:
  -  `app/printer_mqtt_handler.py` — MQTT subscriber that converts JSON messages into a small receipt-style PDF (via ReportLab) and sends it to CUPS using `lp`.
  -  `app/web_control_panel.py` + `app/templates/` — web UI for interacting with printers (UI can publish MQTT commands or call internal APIs).
-  System boundary: printers are managed by CUPS (configured with `configs/cupsd.conf`) and printing is done via command-line tools (`lp`, `lpstat`). The service communicates with Home Assistant (or other clients) over MQTT.

## Key files to inspect
-  `app/printer_mqtt_handler.py` — message schema, env vars, PDF generation (sized for thermal receipts), and printing code paths. Important details:
  -  Env vars: `MQTT_BROKER`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPIC` (defaults to `printer/commands`).
  -  Availability topic: `printer/availability` (published periodically using `lpstat -p`).
  -  PDF saved to `/tmp/print_job.pdf` and printed via `lp -d <printer_name> /tmp/print_job.pdf`.
-  `app/web_control_panel.py` and `app/templates/index.html` — front-end patterns and how users trigger print actions. Use these to see expected payloads and UI expectations.
-  `docker-compose.yml`, `dockerfile`, `entrypoint.sh` — how the project runs containerized. Prefer these for reproducible local testing. **Note:** CUPS configuration (`/etc/cups`) is persisted in a named volume (`cups_config`), so printer settings survive container rebuilds.
-  `configs/cupsd.conf` — CUPS configuration template; copied into the volume on first-run only (see `entrypoint.sh` logic).
-  `entrypoint.sh` — detects first-run vs. subsequent runs via a marker file; initializes CUPS config on first run, preserves it on rebuilds.
-  `README.md` — any existing usage notes; use for merging existing human docs into agent suggestions.

## Message / Payload format (explicit example)
-  Expected payload (JSON) published to `MQTT_TOPIC` (default: `printer/commands`):

  {
    "printer_name": "My_Printer",
    "title": "Shopping List",
    "message": "Apples\nBread\nMilk"
  }

-  `printer_name` is required. The handler uses `title` and `message` to create a short receipt-style PDF.

## Typical developer workflows
-  Local quick run (recommended for development): use the repository's Docker setup for parity with deployment.

  -  Start containers:

    ```bash
    docker-compose up --build
    ```

  -  Or run the MQTT handler directly (useful when iterating on Python code): set env vars and run `python app/printer_mqtt_handler.py`.

-  Publish a test message (example using mosquitto clients):

  ```bash
  mosquitto_pub -h <broker> -t printer/commands -m '{"printer_name":"My_Printer","title":"Test","message":"Line1\nLine2"}'
  ```

-  Debugging tips specific to this repo:
  -  To check CUPS/printer visibility: `lpstat -p` (the handler uses this to set availability). If `lpstat` output doesn't include `idle`, availability will be `offline`.
  -  Check container logs (`docker-compose logs -f`) or Python stdout for JSON parsing errors and printing errors (handler prints subprocess stderr/stdout on failures).
  -  If printing fails, inspect the raw `lp` error printed by `printer_mqtt_handler.py` (see `send_to_printer`).

## Project-specific conventions and patterns
-  Environment-driven configuration: behavior and broker/topic are controlled by env vars rather than CLI flags.
-  Lightweight, single-responsibility scripts: `printer_mqtt_handler.py` focuses on: parse MQTT JSON -> generate PDF -> call `lp`. Keep changes small and test end-to-end.
-  Hard-coded file usage: PDFs are written to `/tmp/print_job.pdf`. When modifying the PDF path, ensure concurrent runs are considered (this repo currently does not serialize or unique-filename print jobs).
-  Minimal external dependencies: uses `paho-mqtt` for MQTT and `reportlab` for PDF generation; printing depends on system CUPS tools (`lp`, `lpstat`).

## Integration points and external dependencies
-  MQTT broker: configurable via `MQTT_BROKER`. Home Assistant or other clients are expected to publish the JSON payload described above.
-  CUPS / system `lp` commands: printers must be configured in the container or host and accessible to the process running the handler. See `configs/cupsd.conf` for service-level config.
-  **CUPS configuration persistence:** The Docker volume `cups_config` mounts to `/etc/cups` in the container. Printer configurations (printers.conf, cupsd.conf, PPD files) are persisted across container rebuilds. On first run, `cupsd.conf` is copied from the `configs/` directory; on subsequent runs, the existing config from the volume is used.
-  The web UI (`app/web_control_panel.py`) is a consumer-style integration; use it to understand the user-facing flows and expected payloads.

## Editing/PR guidance for AI changes
-  When changing printing logic:
  -  Preserve the env-var driven config and availability topic behavior.
  -  Keep PDF page-size logic compatible with small thermal printers (80mm width). See `generate_pdf` in `app/printer_mqtt_handler.py`.
  -  If adding concurrency or queueing, update the README and note possible race on `/tmp/print_job.pdf`.
-  When changing Dockerfiles or `entrypoint.sh`:
  -  Validate locally with `docker-compose up --build` and test printing with a local CUPS instance or by mocking `lp`.
  -  **Avoid overwriting existing CUPS config** on rebuild — the entrypoint uses a marker file (`.printmqttify_initialized`) to detect first-run vs. subsequent runs. Only copy `cupsd.conf` on first run.
  -  To reset CUPS config and start fresh, remove the Docker volume: `docker volume rm printmqttify_cups_config`, then rebuild.

## Quick checklist for a PR
-  Code changes compile / Python lints (run your usual flake8/black locally).
-  Manual test: publish sample MQTT payload and confirm `lp` is invoked and the PDF in `/tmp` looks correct.
-  Update `README.md` if you change user-facing env vars, topics, or add new integration steps.
-  If modifying Docker/entrypoint behavior, test both first-run (`docker-compose up --build`) and subsequent runs (`docker-compose up`) to ensure config persistence works.

If anything here is unclear or you'd like this tailored (for example, to include tests, CI steps, or a mock `lp` harness), tell me which part to expand and I'll iterate.
