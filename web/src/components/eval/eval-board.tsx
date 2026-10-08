"use client";

import { useEffect, useRef, useState } from "react";

import { readApi } from "@/lib/api/client";
import type { EvalReport } from "@/lib/api/types";

type EvalDocument = EvalReport["documents"][number];
import { formatCode, formatPercent } from "@/lib/format";

export function EvalBoard() {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(true);
  const [cleared, setCleared] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const request = useRef(0);

  async function runEvaluation() {
    const id = ++request.current;
    setRunning(true);
    setCleared(false);
    setError(null);
    try {
      const data = await readApi<EvalReport>("/api/eval", { method: "POST" });
      if (request.current !== id) return;
      setReport(data);
      setSelectedId(null);
    } catch (caught) {
      if (request.current !== id) return;
      setReport(null);
      setError(caught instanceof Error ? caught.message : "The evaluation could not be run.");
    } finally {
      if (request.current === id) setRunning(false);
    }
  }

  async function clearReport() {
    const id = ++request.current;
    setBusy(true);
    setRunning(false);
    try {
      await readApi<{ cleared: boolean }>("/api/eval", { method: "DELETE" });
      if (request.current !== id) return;
      setReport(null);
      setError(null);
      setCleared(true);
      setSelectedId(null);
    } catch (caught) {
      if (request.current !== id) return;
      setError(caught instanceof Error ? caught.message : "Could not clear the evaluation.");
    } finally {
      if (request.current === id) setBusy(false);
    }
  }

  useEffect(() => {
    const id = ++request.current;
    readApi<EvalReport>("/api/eval")
      .then((data) => {
        if (request.current === id) setReport(data);
      })
      .catch(() => {
        if (request.current === id) setReport(null);
      })
      .finally(() => {
        if (request.current === id) setRunning(false);
      });
  }, []);

  if (running) {
    return <p className="px-6 py-10 text-sm text-muted">Running the evaluation…</p>;
  }

  if (cleared) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <h1 className="font-serif text-4xl text-ink">Evaluation</h1>
        <p className="mt-4 text-sm leading-6 text-muted">The database is empty. Nothing is stored.</p>
        <button
          type="button"
          onClick={() => void runEvaluation()}
          className="mt-6 rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
        >
          Run evaluation
        </button>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <h1 className="font-serif text-4xl text-ink">Evaluation</h1>
        <p className="mt-4 text-sm leading-6 text-muted">{error}</p>
        <button
          type="button"
          onClick={() => void runEvaluation()}
          className="mt-6 rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
        >
          Try again
        </button>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <h1 className="font-serif text-4xl text-ink">Evaluation</h1>
        <p className="mt-4 text-sm leading-6 text-muted">The database is empty. Nothing is stored.</p>
        <button
          type="button"
          onClick={() => void runEvaluation()}
          className="mt-6 rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
        >
          Run evaluation
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-2xl">
          <h1 className="font-serif text-4xl tracking-tight text-ink sm:text-5xl">Evaluation</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            Field accuracy is the labelled pack. Exception precision and recall score those bundles. The routing
            rates below are generated variants of the clean packet. False auto-clear is a bad invoice that was cleared,
            divided by every automatic clear. Cost is the prompt and completion tokens Ollama used. On the labelled
            pack that cost is zero when the layout reader filled every required field.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void clearReport()}
          disabled={busy}
          className="w-fit self-start rounded-full border border-line bg-card px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
        >
          Clear
        </button>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Metric label="Documents processed" value={String(report.documents_processed)} />
        <Metric label="Field accuracy" value={formatPercent(report.field_accuracy, 1)} />
        <Metric label="Exception precision" value={formatPercent(report.exception_precision, 1)} />
        <Metric label="Exception recall" value={formatPercent(report.exception_recall, 1)} />
        <Metric label="Average latency" value={seconds(report.average_latency_ms)} />
        <Metric label="P95 latency" value={seconds(report.p95_latency_ms)} />
        <Metric label="Average cost / document" value={tokens(averageTokens(report))} />
        <Metric label="Variant cases" value={report.variant_cases == null ? "—" : String(report.variant_cases)} />
        <Metric label="False auto-clear" value={formatPercent(report.false_auto_clear_rate, 1)} />
        <Metric label="Auto-clear precision" value={formatPercent(report.auto_clear_precision, 1)} />
        <Metric label="Auto-clear recall" value={formatPercent(report.auto_clear_recall, 1)} />
        <Metric label="False rejection" value={formatPercent(report.false_rejection_rate, 1)} />
        <Metric label="Human review rate" value={formatPercent(report.human_review_rate, 1)} />
      </section>

      <p className="text-sm text-muted">
        An exception decides first. A price difference, a short delivery, or a GSTIN conflict is reviewed even at a
        high extraction score. An exact duplicate, a missing document, or a failed read is rejected. With no exception,
        auto-clear starts at {formatPercent(report.auto_clear_confidence)}. From {formatPercent(report.flag_confidence)}{" "}
        up to that line the case is reviewed. Below {formatPercent(report.flag_confidence)} it is rejected.
      </p>

      {report.bundles.length === 0 ? (
        <p className="text-sm text-muted">
          This batch did not match a labelled bundle, so exception precision and recall are not scored.
        </p>
      ) : (
      <section className="overflow-x-auto rounded-2xl border border-line bg-card">
        <h2 className="border-b border-line px-4 py-3 text-sm font-medium text-ink">Exception detection</h2>
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead className="text-xs tracking-wide text-muted uppercase">
            <tr>
              <th className="px-4 py-2 font-medium">Bundle</th>
              <th className="px-4 py-2 font-medium">Expected</th>
              <th className="px-4 py-2 font-medium">Predicted</th>
            </tr>
          </thead>
          <tbody>
            {report.bundles.map((bundle) => {
              const same =
                bundle.expected_exceptions.join("|") === bundle.predicted_exceptions.join("|") &&
                bundle.expected_status === bundle.predicted_status;
              return (
                <tr key={bundle.bundle_id} className="border-t border-line">
                  <td className="px-4 py-3">
                    <span className="block text-ink">{bundle.bundle_id}</span>
                    <span className={`text-xs ${same ? "text-accent" : "text-danger"}`}>
                      {same ? "Matched the label" : "Differs from the label"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{codes(bundle.expected_exceptions)}</td>
                  <td className="px-4 py-3 text-ink">{codes(bundle.predicted_exceptions)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      )}

      <section className={selectedId ? "grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]" : ""}>
        <div className="overflow-x-auto rounded-2xl border border-line bg-card">
          <h2 className="border-b border-line px-4 py-3 text-sm font-medium text-ink">Per document</h2>
          <table className="w-full min-w-[44rem] text-left text-sm">
            <thead className="text-xs tracking-wide text-muted uppercase">
              <tr>
                <th className="px-4 py-2 font-medium">Document</th>
                <th className="px-4 py-2 font-medium">Fields</th>
                <th className="px-4 py-2 font-medium">Confidence</th>
                <th className="px-4 py-2 font-medium">Latency</th>
                <th className="px-4 py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {report.documents.map((row) => {
                const selected = row.document_id === selectedId;
                return (
                  <tr key={row.document_id} className={`border-t border-line ${selected ? "bg-stamp" : ""}`}>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        aria-pressed={selected}
                        onClick={() => setSelectedId(selected ? null : row.document_id)}
                        className="text-left"
                      >
                        <span className="block text-ink underline-offset-2 hover:underline">{row.document_id}</span>
                        <span className="text-xs text-muted">{documentMeta(row)}</span>
                      </button>
                      {row.warnings?.[0] ? (
                        <span className="mt-1 block max-w-sm truncate text-xs text-danger" title={row.warnings[0]}>
                          {row.warnings[0]}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      {row.field_total > 0 ? (
                        <>
                          {formatPercent(row.field_accuracy, 1)}
                          <span className="block text-xs text-muted">
                            {row.field_correct}/{row.field_total}
                          </span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3">{formatPercent(row.confidence)}</td>
                    <td className="px-4 py-3">{seconds(row.latency_ms)}</td>
                    <td className="px-4 py-3">{tokens(documentTokens(row))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {selectedId ? (
          <DocumentPreview
            row={report.documents.find((row) => row.document_id === selectedId) ?? null}
            onClose={() => setSelectedId(null)}
          />
        ) : null}
      </section>
    </div>
  );
}

function DocumentPreview({ row, onClose }: { row: EvalDocument | null; onClose: () => void }) {
  if (!row) return null;
  const src = `/backend-api/api/eval/documents/${encodeURIComponent(row.document_id)}`;
  const image = /\.(jpe?g|png|gif|webp)$/i.test(row.document_id);
  return (
    <aside className="sticky top-4 overflow-hidden rounded-2xl border border-line bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">{row.document_id}</p>
          <p className="text-xs text-muted">{documentMeta(row)}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-full border border-line px-3 py-1 text-xs font-medium text-ink hover:bg-paper"
        >
          Close
        </button>
      </div>
      <div className="bg-paper p-3">
        {image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={row.document_id} className="max-h-[70vh] w-full object-contain" />
        ) : (
          <iframe title={row.document_id} src={src} className="h-[70vh] w-full rounded-xl border border-line bg-white" />
        )}
      </div>
    </aside>
  );
}

function documentMeta(row: EvalDocument): string {
  if (row.language && row.language !== "unlabelled") return `${row.presentation} · ${row.language}`;
  return row.presentation;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-card">
      <div className="h-0.5 bg-accent" />
      <div className="px-4 py-3">
        <p className="text-xs text-muted">{label}</p>
        <p className="mt-1 font-serif text-3xl text-ink">{value}</p>
      </div>
    </div>
  );
}

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(2)} sec`;
}

function documentTokens(row: { tokens?: number; input_tokens?: number; output_tokens?: number }): number {
  if (typeof row.tokens === "number") return row.tokens;
  return (row.input_tokens ?? 0) + (row.output_tokens ?? 0);
}

function averageTokens(report: EvalReport): number {
  if (typeof report.average_tokens === "number") return report.average_tokens;
  const rows = report.documents;
  if (rows.length === 0) return 0;
  return rows.reduce((total, row) => total + documentTokens(row), 0) / rows.length;
}

function tokens(count: number): string {
  return `${Math.round(count).toLocaleString("en-US")} tokens`;
}

function codes(values: string[]): string {
  if (values.length === 0) return "none";
  return values.map((value) => formatCode(value)).join(", ");
}
