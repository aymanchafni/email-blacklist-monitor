# Email Attachment Blacklist Monitor

![CI](https://github.com/aymanchafni/email-blacklist-monitor/actions/workflows/ci.yml/badge.svg)

Watches an Outlook / Microsoft 365 inbox through **Microsoft Graph**, extracts text from
incoming attachments (**PDF, Excel, CSV, images via OCR**), matches it against a blacklist
of people and vehicles, and emails an alert when there is a hit.

```
inbox (Graph, paginated) ─► attachments ─► text extraction ─► normalised matching ─► alert email
        ▲                                   PDF · XLSX/XLS · CSV · OCR    CIN · plate · full name
        └──── persistent state: processed message ids + last check time
```

## How matching works

Text from documents is messy, so both the text and the blacklist are **normalised**
(uppercase, accents removed, punctuation and spacing collapsed), then matched on
**token boundaries**:

| Blacklist value | Matches | Does not match |
|---|---|---|
| CIN `ZZ000001` | `zz000001`, `ZZ 000001` | `ZZ0000012` |
| Plate `99999-A-01` | `99999 A 01`, `99999A01`, `99999/a/01` | `199999-A-01` |
| Name `Léa Démo` | `LEA DEMO`, `Démo Léa`, `Léa \| Démo` (two spreadsheet cells) | `Léandre Démo` |

Empty blacklist cells are ignored. The previous version turned them into the string
`"nan"`, which matched words like *financement*.

## Reliability

* **Never misses mail.** It follows Graph pagination, keeps the check cursor in UTC, and
  persists it, so mail received while the monitor is stopped is scanned at the next
  start. The cursor only advances to the start of a poll, with a 5-minute overlap, and
  processed message ids prevent duplicates.
* **Survives token expiry.** A token is requested from MSAL's cache on every call (MSAL
  refreshes it), and a 401 triggers one forced refresh and retry.
* **Failures are retried, not swallowed.** A message whose attachment can't be downloaded
  or parsed isn't marked as processed. It's retried at the next poll, up to 3 attempts.
* **Atomic state file** with 30-day retention for processed ids.

## Setup

1. **Azure app registration** (Azure Portal → App registrations → New registration).
   Supported accounts: *any organizational directory and personal Microsoft accounts*.
   Under **Authentication**, enable *Allow public client flows* (device-code sign-in).
   Under **API permissions**, add the Microsoft Graph *delegated* permissions `Mail.Read`
   and `Mail.Send`.
2. **Install** (Python 3.11+; install [Tesseract](https://github.com/tesseract-ocr/tesseract)
   for image OCR):
   ```bash
   pip install -r requirements.txt
   cp .env.example .env              # fill in CLIENT_ID and ALERT_EMAIL
   cp blacklist.example.csv blacklist.csv
   ```
3. **Blacklist format** (CSV; French/English header variants such as `first name`,
   `prénom` and `vehicule make` are accepted):
   ```csv
   first_name,last_name,cin,vehicle_make,imm,color
   Jane,Example,ZZ000001,Toyota,99999-A-01,Blue
   ```

## Usage

```bash
python -m blacklist_monitor             # poll forever (first run asks you to sign in with a device code)
python -m blacklist_monitor --once      # single poll, e.g. from cron / Task Scheduler
python -m blacklist_monitor --scan report.pdf list.xlsx   # offline check of local files, no email access
```

## Project layout

```
blacklist_monitor/
├── matching.py     normalisation + boundary-aware matching (pure, unit-tested)
├── extraction.py   PDF (PyMuPDF), Excel (openpyxl/xlrd), CSV, OCR (Tesseract)
├── graph.py        MSAL token provider + Graph client (pagination, 401 retry)
├── state.py        processed ids + cursor, atomic JSON
├── monitor.py      poll loop, retries, alert composition
└── __main__.py     CLI
tests/              18 tests: matching rules, real PDF/XLSX/CSV/OCR extraction, monitor with a fake Graph
```

```bash
pip install -r requirements-dev.txt && pytest
```

> The blacklist and state files contain personal data and are git-ignored. Only
> `blacklist.example.csv`, which holds fictitious entries, is versioned.
