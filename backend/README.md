# AP document backend

FastAPI service for the accounts-payable intake flow. It stores documents and fills the schema with a layout reader. A local Ollama model reads the whole page only when a required field is still missing. That extraction is cached in Redis. A LangGraph pipeline then checks the Pydantic schema and runs the match:

`extract → validate → match → classify → route`

A clean, high-confidence match auto-clears. Anything else drafts an email and pauses until a person approves or declines it. Approving records the decision. It does not send the email.

## Run

Redis and Ollama need to be running. Pull the chat model once: `ollama pull llama3.2`. The layout reader does not call it when the page already has every required field.

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000/docs. The website on port 3000 proxies to this API. The browser does not call this process directly. One case can hold 20 files. CORS is open for `localhost:3000`.

```bash
uv run pytest
```

Copy `.env.example` to `.env` to change limits, models, or log level. Settings live in `app/core/config.py`. Logs are configured in `app/core/logging.py` and printed to the terminal. `AP_LOG_LEVEL` is `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. `AP_LOG_FORMAT=json` prints one JSON object per line.

```
app/main.py       process start
app/core/         environment and logging
app/api/          HTTP routes
app/services/     files, cases, intake, cache
app/pipeline/     read, extract, match, route
app/schemas/      data shapes
app/eval/         labelled-pack score
```

A match auto-clears at 0.95 or above when no exception is present. From 0.70 up to that line it is flagged. Below 0.70, or when a document is missing or unreadable, it is rejected. An exact duplicate is the same invoice number, vendor, amount, and purchase order. That is rejected even when the read is strong. The same invoice number with a different vendor or amount is only flagged.

## API

- `GET /health`
- `GET /api/files`, `POST /api/files`, `GET /api/files/{id}`, `DELETE /api/files/{id}`
- `POST /api/runs` with `{ "file_ids": ["..."] }`
- `GET /api/runs/{id}`
- `POST /api/runs/{id}/approval` with `{ "approved": true, "note": "optional" }`

Commercial exceptions (vendor, total, price, quantity, partial delivery) draft a vendor email when the route is `flag`. Extraction failures, missing documents, duplicates, and low-confidence rejects draft an approver email.

## Sample documents

`sample_data/` holds 29 labelled purchase orders, invoices, and goods receipts for Northwind Fabrication. The set includes a clean match, a partial delivery, a wrong invoice total, an exact duplicate, a legal-name variant that still matches, a different vendor, skewed scans, one mixed Hindi-English photograph, and three clean trios at the 100%, 95%, and 90% lines. `ground_truth.json` is the label file. `eval_report.json` is the last score of that pack. Upload one case at a time. The workbench holds 20 files, and matching the whole pack in one case mixes the planted errors together.

```bash
uv run python scripts/generate_sample_data.py
```

## How a decision is made

Digital PDFs are read from the text layer, one page at a time. Photographs go through macOS Vision when it is available, then Tesseract. The layout reader keeps line items from every page and takes the total from the last page that prints one. When a required field is still missing, that text is sent to the chat model, in page groups when the receipt is long. Several documents are read at once. Model calls stay capped. Redis caches a finished model extraction. The matcher compares vendor, currency, quantity, unit price, and totals in code. Header totals use a tolerance of 0.5 percent, with a floor of 1.00 currency unit. Line amounts are treated as pre-tax, and `tax` is added before that comparison. Duplicate invoice numbers are checked inside the submitted set only. Approving a draft stores the decision. Mail is not transmitted.
