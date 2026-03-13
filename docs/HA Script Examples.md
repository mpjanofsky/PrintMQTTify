# Home Assistant Script Examples

PrintMQTTify receives JSON payloads over MQTT. Every example below can be pasted
directly into a Home Assistant automation or script — just update `printer_name` to
match the name configured in your CUPS interface.

---

## Payload Reference

```json
{
  "printer_name": "Epson_TM-m30",
  "title": "Optional title (defaults to current date/time)",
  "subtitle": "Optional subtitle shown flush under the title divider",
  "style": "default",
  "plain_text": false,
  "formatting": {
    "font_size": 10,
    "title_size": 14,
    "show_footer": true,
    "margin_top": 2,
    "margin_bottom": 2,
    "margin_sides": 2,
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
    "caption": "Optional caption below QR"
  }
}
```

**Key rules:**

- `printer_name` is the only required field.
- Use `sections` for structured, multi-area content. Use `message` (a plain string) for
  simple single-block content — it's automatically converted to a single unnamed section.
- `style` sets a named preset; `formatting` fields override individual values on top of it.
- `plain_text: true` disables checkbox/dash parsing — every item prints as raw text.
- `qr_code` can also be a plain string: `"qr_code": "https://example.com"`.
- `subtitle` renders centred in a slightly smaller font immediately below the title divider,
  with a small spacer before the first section. Useful for dates, sub-headings, or short context lines.

### Named Styles

| Style | Description |
|-------|-------------|
| `default` | General purpose, footer shown |
| `compact` | Small font, tight margins, no footer |
| `receipt` | Larger font, generous padding, footer shown |
| `minimal` | Bare-bones, no footer |
| `agenda` | Optimised for multi-section daily schedules |
| `note` | Centred text, generous padding, no footer |

---

## Examples

### 1. Composite Daily Print

The flagship use case: a single morning slip with weather, calendar, tasks, and an
affirmation. Sensor values are templated in by Home Assistant — no special support
needed in PrintMQTTify.

```yaml
alias: Print Daily Agenda
trigger:
  - platform: time
    at: "07:00:00"
action:
  - action: mqtt.publish
    data:
      topic: printer/commands
      payload_template: >
        {
          "printer_name": "Epson_TM-m30",
          "title": "{{ now().strftime('%A, %B %-d') }}",
          "subtitle": "{{ now().strftime('%B %-d, %Y') }}",
          "style": "agenda",
          "sections": [
            {
              "heading": "Good Morning",
              "items": [
                "Today: {{ state_attr('weather.home', 'temperature') }}°F, {{ states('weather.home') }}"
              ]
            },
            {
              "heading": "Tasks",
              "items": [
                {% set ns = namespace(items=[]) %}
                {% for item in state_attr('todo.tasks', 'items') or []
                   if item.status == 'needs_action' %}
                  {% set ns.items = ns.items + ['"[ ] ' ~ item.summary ~ '"'] %}
                {% endfor %}
                {{ ns.items | join(',\n                ') }}
              ]
            },
            {
              "items": [
                "",
                "\"{{ states('input_text.daily_affirmation') }}\""
              ]
            }
          ]
        }
mode: single
```

---

### 2. Shopping List

Print all unchecked items from a Home Assistant todo list, with optional
AI categorization.

#### Basic version

```yaml
alias: Print Shopping List
sequence:
  - data:
      status: needs_action
    target:
      entity_id: todo.shopping_list
    response_variable: list_response
    action: todo.get_items

  - variables:
      items_json: >
        {%- set items = list_response['todo.shopping_list']['items'] -%}
        {%- set ns = namespace(parts=[]) -%}
        {%- for item in items -%}
          {%- set ns.parts = ns.parts + ['"[ ] ' ~ item['summary'] ~ '"'] -%}
        {%- endfor -%}
        {{ ns.parts | join(', ') }}

  - action: mqtt.publish
    data:
      topic: printer/commands
      payload_template: >
        {
          "printer_name": "Epson_TM-m30",
          "title": "Shopping List",
          "style": "receipt",
          "sections": [{ "items": [ {{ items_json }} ] }]
        }
mode: single
```

#### AI-categorized version

Uses an LLM conversation agent to group items by aisle before printing.

```yaml
alias: Print Categorized Shopping List
sequence:
  - data:
      status: needs_action
    target:
      entity_id: todo.shopping_list
    response_variable: list_response
    action: todo.get_items

  - variables:
      item_names: >
        {%- set items = list_response['todo.shopping_list']['items'] -%}
        {{ items | map(attribute='summary') | join(', ') }}

  - service: conversation.process
    data:
      text: >
        Categorize these grocery items by store section, using short category
        headings. Format as: Category:\n- item\n- item\n\nNext Category:\n...
        Items: {{ item_names }}
      agent_id: conversation.chatgpt
    response_variable: categorized_response

  - action: mqtt.publish
    data:
      topic: printer/commands
      payload_template: >
        {
          "printer_name": "Epson_TM-m30",
          "title": "Shopping List",
          "style": "receipt",
          "message": "{{ categorized_response.response.speech.plain.speech | replace('\n','\\n') | replace('"','\\"') }}"
        }
mode: single
```

---

### 3. WiFi Guest Slip

Print a welcome slip with the WiFi password encoded as a QR code. Trigger from a
button on your dashboard or via a door sensor automation.

```yaml
alias: Print WiFi Guest Slip
action:
  - action: mqtt.publish
    data:
      topic: printer/commands
      payload: >
        {
          "printer_name": "Epson_TM-m30",
          "title": "Welcome!",
          "style": "receipt",
          "sections": [
            { "items": ["Join our WiFi:"] }
          ],
          "qr_code": {
            "content": "WIFI:S:YourNetworkName;T:WPA;P:YourPassword;;",
            "size": "large",
            "caption": "Scan to connect"
          }
        }
```

> **WiFi QR format:** `WIFI:S:<SSID>;T:<WPA|WEP|nopass>;P:<password>;;`

---

### 4. Ad-hoc Note

A quick one-off plain-text message. Wire this to a dashboard button, a voice command,
or any other trigger.

```yaml
alias: Print Quick Note
fields:
  message:
    description: The message to print
    example: "Don't forget to take out the trash!"
action:
  - action: mqtt.publish
    data:
      topic: printer/commands
      payload_template: >
        {
          "printer_name": "Epson_TM-m30",
          "message": "{{ message }}",
          "style": "minimal",
          "plain_text": true
        }
```

---

### 5. Gratitude / Daily Affirmation

Print a centred inspirational note. Pair with an `input_text` helper in HA to rotate
quotes, or use a fixed message.

```yaml
alias: Print Morning Affirmation
trigger:
  - platform: time
    at: "07:05:00"
action:
  - action: mqtt.publish
    data:
      topic: printer/commands
      payload_template: >
        {
          "printer_name": "Epson_TM-m30",
          "style": "note",
          "sections": [
            {
              "items": [
                "{{ now().strftime('%A, %B %-d') }}",
                "",
                "\"{{ states('input_text.daily_affirmation') }}\""
              ]
            }
          ]
        }
```

---

### 6. Food Label / Meal Prep Tag

Print a small label with the date made and use-by date. Trigger from a dashboard
button when packing food containers.

```yaml
alias: Print Food Label
fields:
  item_name:
    description: What was made
    example: "Chicken soup"
  use_by_days:
    description: How many days until it expires
    example: 4
action:
  - action: mqtt.publish
    data:
      topic: printer/commands
      payload_template: >
        {
          "printer_name": "Epson_TM-m30",
          "style": "compact",
          "sections": [
            {
              "items": [
                "{{ item_name }}",
                "Made:    {{ now().strftime('%m/%d/%Y') }}",
                "Use by:  {{ (now() + timedelta(days=use_by_days | int)).strftime('%m/%d/%Y') }}"
              ]
            }
          ]
        }
```

---

### 7. Game Night Scoreboard

Print scores on demand during game night. Store each player's score in an
`input_number` helper and trigger from a dashboard button.

```yaml
alias: Print Scoreboard
action:
  - action: mqtt.publish
    data:
      topic: printer/commands
      payload_template: >
        {
          "printer_name": "Epson_TM-m30",
          "title": "Scoreboard",
          "style": "receipt",
          "sections": [
            {
              "heading": "{{ now().strftime('%I:%M %p') }}",
              "items": [
                "Alice:   {{ states('input_number.score_alice') | int }} pts",
                "Bob:     {{ states('input_number.score_bob') | int }} pts",
                "Charlie: {{ states('input_number.score_charlie') | int }} pts"
              ]
            }
          ]
        }
```

---

### 8. Leaving-Home Checklist

Triggered when everyone leaves the house (e.g., all device trackers go `not_home`).
Prints a quick checklist at the door.

```yaml
alias: Print Leaving-Home Checklist
trigger:
  - platform: state
    entity_id: group.all_people
    to: not_home
action:
  - action: mqtt.publish
    data:
      topic: printer/commands
      payload: >
        {
          "printer_name": "Epson_TM-m30",
          "title": "Before You Leave",
          "style": "minimal",
          "sections": [
            {
              "items": [
                "[ ] Keys",
                "[ ] Wallet / phone",
                "[ ] Charger",
                "[ ] Dog walked?",
                "[ ] Stove off?"
              ]
            }
          ]
        }
```

---

## Tips

**Sensor values anywhere** — Any HA entity state or attribute can appear inside a
section item via `payload_template`:
```
"Today: {{ states('sensor.living_room_temperature') }}°F"
```

**Blank lines** — An empty string `""` in an items array inserts a blank line.

**Combining style + override** — Use a named style as a base and tweak one value:
```json
"style": "agenda",
"formatting": { "font_size": 10, "show_footer": true }
```

**QR code shorthand** — For a URL-only QR, pass a plain string:
```json
"qr_code": "https://ha.example.com/lovelace/main"
```

**Subtitle** — Add a secondary line flush under the title divider. Great for dates or context:
```json
"title": "Morning Briefing",
"subtitle": "{{ now().strftime('%A, %B %-d, %Y') }}"
```
The subtitle renders centred in a slightly smaller font (`title_size - 2 pt`) with a small spacer before the first section begins.
