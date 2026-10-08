"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { readApi } from "@/lib/api/client";
import type { EmailDraft, RuleResult, RunView } from "@/lib/api/types";
import { formatCode, formatMoney, formatPercent, routingLabel } from "@/lib/format";

type CaseReviewProps = {
  run: RunView | null;
  loading: boolean;
  fileSelected: boolean;
  hasFiles: boolean;
  onChange: (run: RunView) => void;
};

export function CaseReview({ run, loading, fileSelected, hasFiles, onChange }: CaseReviewProps) {
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<CaseTab>("summary");
  const [openScore, setOpenScore] = useState<string | null>("routing_score");
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [failedOnly, setFailedOnly] = useState(false);
  const [chooseMail, setChooseMail] = useState(false);
  const draftReady = run?.email_draft ? run.id : null;

  useEffect(() => {
    if (!draftReady) return;
    document.getElementById("draft-email")?.scrollIntoView({ block: "nearest" });
  }, [draftReady]);

  if (loading) {
    return <Panel message="Opening the case…" />;
  }
  if (!run) {
    if (fileSelected) {
      return (
        <Panel message="Select a case to see the three-way match, the routing decision, and any draft that is waiting for you." />
      );
    }
    return (
      <Panel
        message={
          hasFiles
            ? "Select an uploaded file."
            : "Upload a purchase order, invoice, and goods receipt. Matching starts in the background."
        }
      />
    );
  }

  const match = run.match;
  const currency = match?.currency ?? null;
  const draft = run.email_draft;

  function beginEdit() {
    if (!draft) return;
    setSubject(draft.subject);
    setBody(draft.body);
    setEditing(true);
    setError(null);
  }

  async function saveDraft() {
    if (!run) return;
    setBusy("Saving draft…");
    setError(null);
    try {
      const updated = await readApi<RunView>(`/api/runs/${run.id}/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject, body }),
      });
      setEditing(false);
      onChange(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the draft.");
    } finally {
      setBusy(null);
    }
  }

  async function decide(approved: boolean) {
    if (!run) return;
    setBusy(approved ? "Recording approval…" : "Recording the decline…");
    setError(null);
    try {
      const payload: { approved: boolean; note: string | null; email_draft?: EmailDraft } = {
        approved,
        note: note.trim() || null,
      };
      if (draft && editing) {
        payload.email_draft = { ...draft, subject, body };
      }
      const updated = await readApi<RunView>(`/api/runs/${run.id}/approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setEditing(false);
      setNote("");
      onChange(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not record the decision.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="flex flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs tracking-[0.16em] text-muted uppercase">
            {match?.invoice_number ? `Invoice ${match.invoice_number}` : "Case"}
          </p>
          <h2 className="mt-1 font-serif text-3xl text-ink">{match?.vendor_name ?? "Unreadable set"}</h2>
          <p className="mt-2 text-sm text-muted">
            PO {match?.po_number ?? "—"}
            <span className="px-2 text-line">|</span>
            GRN {match?.grn_number ?? "—"}
          </p>
        </div>
        <DecisionBadge routing={run.routing} confidence={run.confidence} scores={run.scores} />
      </header>

      <dl className="grid grid-cols-3 gap-3">
        <Amount label="Purchase order" value={formatMoney(match?.po_total, currency)} />
        <Amount label="Invoice" value={formatMoney(match?.invoice_total, currency)} />
        <Amount label="Goods received" value={formatMoney(match?.grn_total, currency)} />
      </dl>

      <div role="tablist" aria-label="Case detail" className="flex flex-wrap gap-1">
        {(
          [
            ["summary", "Summary"],
            ["checks", "Checks"],
            ["lines", "Lines"],
            ["letter", "Letter"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => {
              setTab(id);
              if (id === "letter") {
                document.getElementById("draft-email")?.scrollIntoView({ block: "nearest" });
              }
            }}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === id ? "bg-accent text-white" : "border border-line bg-card text-muted hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {(tab === "summary" || tab === "letter") && draft ? (
        <section id="draft-email" className="rounded-2xl border border-line bg-card">
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
            <div>
              <h3 className="text-sm font-medium text-ink">
                Draft to the {draft.to_role === "vendor" ? "vendor" : "approver"}
              </h3>
              <p className="mt-1 text-xs leading-5 text-muted">
                Generate email opens a preview. Edit the letter there, then send it via Gmail or Hotmail.
              </p>
            </div>
            {run.awaiting_approval && !editing ? (
              <button
                type="button"
                onClick={beginEdit}
                className="rounded-full border border-line px-3 py-1.5 text-xs font-medium text-ink"
              >
                Edit draft
              </button>
            ) : null}
          </div>
          <div className="px-4 py-3">
            {editing ? (
              <div className="flex flex-col gap-3">
                <label className="text-xs text-muted">
                  Subject
                  <input
                    value={subject}
                    onChange={(event) => setSubject(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-line bg-paper px-3 py-2 text-sm text-ink"
                  />
                </label>
                <label className="text-xs text-muted">
                  Body
                  <textarea
                    value={body}
                    onChange={(event) => setBody(event.target.value)}
                    rows={16}
                    className="mt-1 w-full rounded-xl border border-line bg-paper px-3 py-2 text-sm leading-6 text-ink"
                  />
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void saveDraft()}
                    disabled={busy !== null || !subject.trim() || !body.trim()}
                    className="rounded-full bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
                  >
                    Save draft
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(false)}
                    className="rounded-full border border-line px-3 py-1.5 text-xs font-medium text-ink"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    aria-haspopup="dialog"
                    onClick={() => setChooseMail(true)}
                    className="rounded-full bg-accent px-3 py-1.5 text-xs font-medium text-white"
                  >
                    Generate email
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <p className="text-sm font-medium text-ink">{draft.subject}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    aria-haspopup="dialog"
                    onClick={() => setChooseMail(true)}
                    className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
                  >
                    Generate email
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>
      ) : tab === "letter" ? (
        <p className="rounded-2xl border border-line bg-stamp px-4 py-3 text-sm text-accent">
          {run.routing === "auto_clear"
            ? "This set auto-cleared. No email was drafted, and nothing is waiting for approval."
            : "No email was drafted for this case."}
        </p>
      ) : null}

      {tab === "summary" ? (
        <>
          <p className="text-sm leading-6 text-ink">{match?.summary}</p>
          {run.scores ? (
            <ScoreMeters scores={run.scores} open={openScore} onOpen={setOpenScore} />
          ) : null}
          {run.exceptions.length > 0 ? (
            <section>
              <h3 className="text-sm font-medium text-ink">Exceptions</h3>
              <ul className="mt-2 flex flex-col gap-2">
                {run.exceptions.map((item) => (
                  <li key={item.type} className="rounded-xl border border-line bg-card px-3 py-2">
                    <p className="text-xs tracking-wide text-muted uppercase">
                      {formatCode(item.type)} · {item.severity}
                    </p>
                    <p className="mt-1 text-sm leading-6 text-ink">{item.message}</p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {run.extractions.length > 0 ? (
            <section>
              <h3 className="text-sm font-medium text-ink">Source documents</h3>
              <p className="mt-1 text-xs text-muted">Click a file to open it here.</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {run.extractions.map((item) => {
                  const open = previewId === item.file_id;
                  return (
                    <li key={item.file_id}>
                      <button
                        type="button"
                        aria-pressed={open}
                        title={item.warnings?.[0]}
                        onClick={() => setPreviewId(open ? null : item.file_id)}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs text-ink ${
                          open ? "border-accent bg-stamp" : "border-line bg-card hover:border-accent"
                        }`}
                      >
                        <span>{item.source_name ?? item.file_id}</span>
                        {item.extractor ? <span className="text-muted">{item.extractor}</span> : null}
                        <span className="text-muted">{formatPercent(item.confidence)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {previewId ? <DocumentPreview fileId={previewId} name={previewName(run, previewId)} /> : null}
            </section>
          ) : null}
        </>
      ) : null}

      {tab === "checks" ? (
        match?.rules && match.rules.length > 0 ? (
          <section>
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium text-ink">Rule results</h3>
              <button
                type="button"
                aria-pressed={failedOnly}
                onClick={() => setFailedOnly((current) => !current)}
                className={`rounded-full border px-3 py-1 text-xs font-medium ${
                  failedOnly ? "border-accent bg-stamp text-ink" : "border-line text-muted"
                }`}
              >
                {failedOnly ? "Showing failures" : "Show failures only"}
              </button>
            </div>
            <ul className="mt-2 divide-y divide-line overflow-hidden rounded-2xl border border-line">
              {match.rules
                .filter((rule) => !failedOnly || rule.status !== "PASS")
                .map((rule, index) => (
                  <RuleRow key={`${rule.rule}-${index}`} rule={rule} />
                ))}
            </ul>
            {failedOnly && match.rules.every((rule) => rule.status === "PASS") ? (
              <p className="mt-2 text-sm text-muted">Every check passed.</p>
            ) : null}
          </section>
        ) : (
          <section>
            <h3 className="text-sm font-medium text-ink">Match checks</h3>
            <ul className="mt-2 divide-y divide-line overflow-hidden rounded-2xl border border-line">
              {(match?.checks ?? []).map((check) => (
                <li key={check.label} className="flex items-center gap-3 bg-card px-3 py-2.5 text-sm">
                  <span
                    className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
                      check.passed ? "bg-stamp text-accent" : "bg-danger-wash text-danger"
                    }`}
                    aria-hidden
                  >
                    {check.passed ? "✓" : "✗"}
                  </span>
                  <span className={check.passed ? "text-ink" : "text-danger"}>{check.label}</span>
                </li>
              ))}
            </ul>
          </section>
        )
      ) : null}

      {tab === "lines" ? (
        match && match.lines.length > 0 ? (
          <section className="overflow-x-auto rounded-2xl border border-line">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="bg-paper text-xs tracking-wide text-muted uppercase">
                <tr>
                  <th className="px-3 py-2 font-medium">Item</th>
                  <th className="px-3 py-2 font-medium">PO qty</th>
                  <th className="px-3 py-2 font-medium">Invoice qty</th>
                  <th className="px-3 py-2 font-medium">Received</th>
                  <th className="px-3 py-2 font-medium">PO price</th>
                  <th className="px-3 py-2 font-medium">Invoice price</th>
                </tr>
              </thead>
              <tbody>
                {match.lines.map((line) => {
                  const max = Math.max(
                    asNumber(line.po_quantity),
                    asNumber(line.invoice_quantity),
                    asNumber(line.received_quantity),
                    1,
                  );
                  return (
                    <tr key={line.key} className="border-t border-line bg-card">
                      <td className="px-3 py-2">
                        <span className="block text-ink">{line.description}</span>
                        {line.notes.map((note) => (
                          <span key={note} className="mt-1 block text-xs text-danger">
                            {note}
                          </span>
                        ))}
                      </td>
                      <QtyCell value={line.po_quantity} max={max} tone="bg-accent" />
                      <QtyCell value={line.invoice_quantity} max={max} tone="bg-warn" />
                      <QtyCell value={line.received_quantity} max={max} tone="bg-accent/70" />
                      <td className="px-3 py-2">{formatMoney(line.po_unit_price, currency)}</td>
                      <td className="px-3 py-2">{formatMoney(line.invoice_unit_price, currency)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        ) : (
          <p className="text-sm text-muted">This case has no line comparison.</p>
        )
      ) : null}

      {run.awaiting_approval ? (
        <section className="flex flex-col gap-3">
          <label className="text-xs text-muted">
            Note for the case file
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Optional"
              className="mt-1 w-full rounded-xl border border-line bg-card px-3 py-2 text-sm text-ink"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void decide(true)}
              disabled={busy !== null}
              className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => void decide(false)}
              disabled={busy !== null}
              className="rounded-full border border-danger/30 px-4 py-2 text-sm font-medium text-danger disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </section>
      ) : run.approval ? (
        <p className="text-sm text-ink">
          Decision recorded: {run.approval.approved ? "approved" : "declined"}
          {run.approval.note ? ` — ${run.approval.note}` : ""}.
        </p>
      ) : null}

      {chooseMail && draft ? (
        <EmailPreview
          toRole={draft.to_role}
          subject={editing ? subject : draft.subject}
          body={editing ? body : draft.body}
          onClose={() => setChooseMail(false)}
          onSave={
            run.awaiting_approval
              ? async (nextSubject, nextBody) => {
                  const updated = await readApi<RunView>(`/api/runs/${run.id}/draft`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ subject: nextSubject, body: nextBody }),
                  });
                  setSubject(nextSubject);
                  setBody(nextBody);
                  onChange(updated);
                }
              : undefined
          }
        />
      ) : null}

      {busy ? <p className="text-sm text-muted">{busy}</p> : null}
      {error ? (
        <p role="alert" className="rounded-xl border border-danger/20 bg-danger-wash px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </article>
  );
}

function DecisionBadge({
  routing,
  confidence,
  scores,
}: {
  routing: RunView["routing"];
  confidence: number | null;
  scores: RunView["scores"];
}) {
  const tone =
    routing === "auto_clear"
      ? "border-accent/20 bg-stamp text-accent"
      : routing === "flag"
        ? "border-warn/20 bg-warn-wash text-warn"
        : "border-danger/20 bg-danger-wash text-danger";
  return (
    <div className={`rounded-2xl border px-4 py-3 text-right ${tone}`}>
      <p className="text-xs tracking-[0.14em] uppercase">Decision</p>
      <p className="mt-1 font-serif text-2xl">{routingLabel(routing)}</p>
      <p className="mt-1 text-xs">Routing score {formatPercent(scores?.routing_score ?? confidence)}</p>
      <p className="mt-1 text-xs">Extraction {formatPercent(scores?.extraction ?? confidence)}</p>
    </div>
  );
}

type CaseTab = "summary" | "checks" | "lines" | "letter";

const SCORE_COPY: Record<string, string> = {
  completeness:
    "Share of required fields found on the weakest document: number, vendor, total, currency, lines, and a purchase-order reference on the invoice and goods receipt.",
  extraction:
    "Trust in the characters. A complete text layer is 100%. A text layer with no issue date is 95%. A photograph is capped at 90%, so it cannot auto-clear. A model fill is capped at 85%.",
  validation: "Whether each document agrees with itself. A header total that does not match its own lines lowers this.",
  matching:
    "Whether the purchase order, invoice, and goods receipt agree. A high-severity failure pulls this to 40%. A softer failure sits at 75%. Full agreement is 100%.",
  routing_score:
    "The weakest of the four scores. With no exception, 95% or above auto-clears, 70% up to 95% is reviewed, and below 70% is rejected.",
};

function ScoreMeters({
  scores,
  open,
  onOpen,
}: {
  scores: NonNullable<RunView["scores"]>;
  open: string | null;
  onOpen: (key: string | null) => void;
}) {
  const rows = [
    ["completeness", "Completeness", scores.completeness],
    ["extraction", "Extraction", scores.extraction],
    ["validation", "Validation", scores.validation],
    ["matching", "Match", scores.matching],
    ["routing_score", "Routing score", scores.routing_score],
  ] as const;
  return (
    <div className="rounded-2xl border border-line bg-card px-3 py-3">
      <p className="text-xs text-muted">Click a score to read what it measures.</p>
      <ul className="mt-3 flex flex-col gap-3">
        {rows.map(([key, label, value]) => {
          const selected = open === key;
          return (
            <li key={key}>
              <button
                type="button"
                aria-expanded={selected}
                onClick={() => onOpen(selected ? null : key)}
                className="w-full text-left"
              >
                <span className="flex items-center justify-between text-xs text-ink">
                  <span>{label}</span>
                  <span>{formatPercent(value)}</span>
                </span>
                <span className="relative mt-1 block h-1.5 overflow-hidden rounded-full bg-line">
                  <span
                    className={`block h-full rounded-full ${key === "routing_score" ? "bg-accent" : "bg-accent/80"}`}
                    style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }}
                  />
                  {key === "routing_score" ? (
                    <>
                      <span className="absolute top-0 bottom-0 left-[70%] w-px bg-warn" />
                      <span className="absolute top-0 bottom-0 left-[95%] w-px bg-accent" />
                    </>
                  ) : null}
                </span>
              </button>
              {selected ? <p className="mt-1 text-xs leading-5 text-muted">{SCORE_COPY[key]}</p> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RuleRow({ rule }: { rule: RuleResult }) {
  const [open, setOpen] = useState(false);
  const detail = rule.expected || rule.actual;
  return (
    <li className="bg-card text-sm">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left"
      >
        <span className="text-ink">{formatCode(rule.rule)}</span>
        <span className={ruleTone(rule.status)}>{rule.status}</span>
      </button>
      {open ? (
        <div className="px-3 pb-2.5">
          <p className="text-xs leading-5 text-muted">{rule.reason}</p>
          {detail ? (
            <p className="mt-1 text-xs text-muted">
              Expected {rule.expected ?? "—"}
              <span className="px-2 text-line">|</span>
              Actual {rule.actual ?? "—"}
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function QtyCell({ value, max, tone }: { value: string | number | null; max: number; tone: string }) {
  const numeric = asNumber(value);
  const width = max > 0 ? Math.max(0, Math.min(100, (numeric / max) * 100)) : 0;
  return (
    <td className="px-3 py-2">
      <span className="block">{showQty(value)}</span>
      <span className="mt-1 block h-1.5 w-16 overflow-hidden rounded-full bg-line" aria-hidden>
        <span className={`block h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
      </span>
    </td>
  );
}

function DocumentPreview({ fileId, name }: { fileId: string; name: string }) {
  const href = `/backend-api/api/files/${fileId}`;
  const kind = previewKind(name);
  return (
    <div className="mt-3 overflow-hidden rounded-2xl border border-line bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
        <p className="truncate text-xs text-ink">{name}</p>
        <a href={href} target="_blank" rel="noreferrer" className="text-xs text-muted underline">
          Open in a new tab
        </a>
      </div>
      {kind === "image" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={href} alt={name} className="max-h-[32rem] w-full bg-paper object-contain" />
      ) : kind === "pdf" ? (
        <iframe title={name} src={href} className="h-[32rem] w-full bg-paper" />
      ) : (
        <p className="px-3 py-4 text-sm text-muted">This file type does not preview here.</p>
      )}
    </div>
  );
}

function previewName(run: RunView, fileId: string): string {
  return run.extractions.find((item) => item.file_id === fileId)?.source_name ?? fileId;
}

function previewKind(name: string): "image" | "pdf" | "other" {
  const lower = name.toLowerCase();
  if (/\.(png|jpe?g|webp|gif|tif|tiff)$/.test(lower)) return "image";
  if (lower.endsWith(".pdf")) return "pdf";
  return "other";
}

function asNumber(value: string | number | null): number {
  if (value == null || value === "") return 0;
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function EmailPreview({
  toRole,
  subject,
  body,
  onClose,
  onSave,
}: {
  toRole: EmailDraft["to_role"];
  subject: string;
  body: string;
  onClose: () => void;
  onSave?: (subject: string, body: string) => Promise<void>;
}) {
  const [draftSubject, setDraftSubject] = useState(subject);
  const [draftBody, setDraftBody] = useState(body);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const initial = useState({ subject, body })[0];

  async function persist(): Promise<boolean> {
    if (!onSave) return true;
    if (draftSubject === initial.subject && draftBody === initial.body) return true;
    if (!draftSubject.trim() || !draftBody.trim()) {
      setSaveError("Subject and message are both required.");
      return false;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(draftSubject, draftBody);
      return true;
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : "Could not save the draft.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function close() {
    if (saving) return;
    if (await persist()) onClose();
  }

  function send(app: "gmail" | "hotmail") {
    if (saving || !draftSubject.trim() || !draftBody.trim()) return;
    window.open(composeUrl(app, draftSubject, draftBody), "_blank", "noopener,noreferrer");
    void persist();
  }

  const closeRef = useRef(close);
  closeRef.current = close;

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") void closeRef.current();
    }
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, []);

  const canSend = draftSubject.trim().length > 0 && draftBody.trim().length > 0 && !saving;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" onClick={() => void close()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="email-preview-title"
        className="flex max-h-[min(44rem,calc(100vh-2rem))] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-line bg-card shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h3 id="email-preview-title" className="font-serif text-2xl text-ink">
              Email preview
            </h3>
            <p className="mt-1 text-xs text-muted">Edit the letter here. Nothing is sent until you choose Gmail or Hotmail.</p>
          </div>
          <button
            type="button"
            onClick={() => void close()}
            disabled={saving}
            className="rounded-full border border-line px-3 py-1.5 text-xs font-medium text-ink disabled:opacity-50"
          >
            Close
          </button>
        </div>
        <div className="flex flex-col gap-4 overflow-y-auto px-5 py-4">
          <div>
            <p className="text-xs tracking-wide text-muted uppercase">To</p>
            <p className="mt-1 text-sm text-ink">{toRole === "vendor" ? "Vendor" : "Approver"}</p>
          </div>
          <label className="text-xs tracking-wide text-muted uppercase">
            Subject
            <input
              value={draftSubject}
              onChange={(event) => setDraftSubject(event.target.value)}
              className="mt-1 w-full rounded-xl border border-line bg-paper px-3 py-2 text-sm font-medium tracking-normal text-ink normal-case"
            />
          </label>
          <label className="text-xs tracking-wide text-muted uppercase">
            Message
            <textarea
              value={draftBody}
              onChange={(event) => setDraftBody(event.target.value)}
              rows={12}
              className="mt-1 w-full rounded-xl border border-line bg-paper px-3 py-2 text-sm leading-6 tracking-normal text-ink normal-case"
            />
          </label>
          {saveError ? (
            <p role="alert" className="text-sm text-danger">
              {saveError}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2 border-t border-line px-5 py-4">
          <button
            type="button"
            onClick={() => void send("gmail")}
            disabled={!canSend}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            Send via Gmail
          </button>
          <button
            type="button"
            onClick={() => void send("hotmail")}
            disabled={!canSend}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            Send via Hotmail
          </button>
          {saving ? <p className="self-center text-xs text-muted">Saving draft…</p> : null}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function composeUrl(app: "gmail" | "hotmail", subject: string, body: string): string {
  const su = encodeURIComponent(subject);
  const text = encodeURIComponent(body);
  if (app === "gmail") {
    return `https://mail.google.com/mail/?view=cm&fs=1&su=${su}&body=${text}`;
  }
  return `https://outlook.live.com/mail/0/deeplink/compose?subject=${su}&body=${text}`;
}

function ruleTone(status: "PASS" | "FAIL" | "WARN"): string {
  if (status === "PASS") return "text-xs font-medium text-accent";
  if (status === "WARN") return "text-xs font-medium text-warn";
  return "text-xs font-medium text-danger";
}

function Amount({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-line bg-card px-3 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

function Panel({ message }: { message: string }) {
  return (
    <div className="flex min-h-[28rem] items-center rounded-2xl border border-dashed border-line bg-card px-6 py-10">
      <p className="max-w-md text-sm leading-6 text-muted">{message}</p>
    </div>
  );
}

function showQty(value: string | number | null): string {
  if (value == null || value === "") return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(numeric);
}
