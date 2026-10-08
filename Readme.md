# PROBLEM

Our AP team at a mid-size manufacturer spends 3 days a month chasing invoice mismatches. Build something that helps." Give them about 20 sample documents: purchase orders, invoices, goods receipt notes, a few scanned or skewed copies, one in Hindi or a mixed language, and some with deliberate errors (wrong totals, duplicate invoice numbers, a vendor-name mismatch, partial delivery).
What they must deliver:
* Extraction into a validated schema (Pydantic or Zod), plus a three-way match between PO, invoice and goods receipt.
* A LangGraph (or similar) flow: extract → validate → match → classify the exception → draft an email to the vendor or approver. A human approves anything that writes or sends.
* Confidence-based routing: auto-clear, flag, or reject.
* A small eval harness: a labelled ground-truth set, field-level accuracy, exception-detection precision and recall, and cost and latency per document.
* A one-page "client readout" covering what was assumed, what they would ask the AP head, and what isn't production-ready.

## Stack

We needed three things: a checked form for each document, a step-by-step flow that waits for a person before anything is sent, and a score against known answers.

### The server

**Python** runs the backend. The check, the match, and the score all live in one place.

**uv** installs the Python packages. Your machine and Docker use the same list, so they run the same code.

**FastAPI** is the web API. The page uploads files, starts a run, and sends the approve or reject click here. **Uvicorn** is the program that runs that API.

**Pydantic** checks that each document has the fields we need, such as vendor, date, and total. If a field is wrong or missing, the case is flagged. It is never auto-cleared. The 0.95 and 0.70 cutoffs come from settings, so we can change them without editing code.

### Reading the document

**pypdfium2** pulls the real text out of a normal PDF. We try this first because it is free and exact. On the sample set this was enough, so we never had to call the language model.

**macOS Vision** reads photos when the app runs on a Mac. It handles English and Hindi, which we need for the mixed-language invoice. We use the normal processor because the special chip on this Mac failed on these images.

**Tesseract** reads photos inside Docker. Docker is Linux, and it does not have macOS Vision. We installed English and Hindi.

**Ollama** with **llama3.2** is a language model that stays on this machine. We call it only when a needed field is still blank. The document never leaves the computer. **Redis** remembers that answer for seven days, so the same file is not sent to the model again. If Redis is down, the run still works.

### The match, and the wait for a person

**LangGraph** is the step list. It reads the file, checks it, matches the purchase order with the invoice and the goods receipt, scores it, then decides. A clean match at 0.95 or higher is cleared. Anything else gets a draft email and stops. A person approves or declines. We save that choice. We do not send the email.

The match itself is plain Python. We compare vendor, currency, quantity, price, and totals, and we allow a small difference. The score stays the same every time.

**SQLite** saves the run while it waits for that person. You can close the page and come back. The case is still there.

### Tests and sample files

**pytest** runs the tests. **httpx** calls the API inside those tests, the way a browser would.

**ReportLab** makes the sample PDFs. **Pillow** makes the photo copies. One script can rebuild the whole set. The answer key stays in `ground_truth.json`. The score checks whether the fields are right, whether we catch real problems, and how long each document took.

### The review page

**Next.js**, **React**, and **TypeScript** are the website. That is the queue, the case, the score page, and the client note. The website talks to the API for you. The browser does not call the Python server on its own.

**Tailwind** styles the pages. It is enough for this small screen.

### How we start it

**Docker Compose** starts Redis, the API, and the website together. The language model stays on your Mac. Docker only calls it there.

The high-level design, with the architecture and the flow, is in [HLD.md](HLD.md).

