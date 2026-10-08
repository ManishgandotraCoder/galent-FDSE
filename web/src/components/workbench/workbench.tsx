"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readApi } from "@/lib/api/client";
import type { FileList, IntakeStatus, RunSummary, RunView, StoredFile } from "@/lib/api/types";
import { caseTitle, formatHours, formatPercent, minutesSaved, routingLabel } from "@/lib/format";
import { CaseReview } from "./case-review";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.gif,.tif,.tiff,.txt,.csv";

export function Workbench() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [files, setFiles] = useState<FileList["files"]>([]);
  const [limit, setLimit] = useState(20);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<RunView | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingCase, setLoadingCase] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [intake, setIntake] = useState<IntakeStatus | null>(null);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");
  const [dragging, setDragging] = useState(false);

  const refreshLists = useCallback(async () => {
    const [runList, fileList] = await Promise.all([
      readApi<{ runs: RunSummary[] }>("/api/runs"),
      readApi<FileList>("/api/files"),
    ]);
    setRuns(runList.runs);
    setFiles(fileList.files);
    setLimit(fileList.limit);
    setOffline(false);
    return runList.runs;
  }, []);

  const openCase = useCallback(async (id: string) => {
    setActiveId(id);
    setLoadingCase(true);
    try {
      const view = await readApi<RunView>(`/api/runs/${id}`);
      setActive(view);
      setOffline(false);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Could not open that case.");
    } finally {
      setLoadingCase(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        await refreshLists();
        if (cancelled) return;
      } catch {
        if (!cancelled) {
          setOffline(true);
          setNotice("Start the API on port 8000, then reload this page.");
        }
      } finally {
        if (!cancelled) setLoadingList(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshLists]);

  useEffect(() => {
    let cancelled = false;
    let primed = false;
    let seenRun: string | null = null;

    async function poll() {
      try {
        const job = await readApi<IntakeStatus>("/api/intake");
        if (cancelled) return;
        setIntake(job);
        if (!primed) {
          primed = true;
          seenRun = job.run_id;
          return;
        }
        if (job.status === "done" && job.run_id && job.run_id !== seenRun) {
          seenRun = job.run_id;
          await refreshLists();
        }
      } catch {
        // The status button reports the API on its own.
      }
    }

    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshLists]);

  const canClear = files.length > 0 || runs.length > 0 || intake?.status === "running";

  async function clearDesk() {
    setBusy("Clearing…");
    setNotice(null);
    try {
      await readApi<{ cleared: boolean }>("/api/clear", { method: "POST" });
      setFiles([]);
      setRuns([]);
      setSelectedIds([]);
      setActive(null);
      setActiveId(null);
      setActiveFileId(null);
      setIntake(null);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Could not clear the workbench.");
    } finally {
      setBusy(null);
    }
  }

  async function upload(incoming: File[]) {
    if (incoming.length === 0) return;
    setBusy("Uploading…");
    setNotice(null);
    try {
      const body = new FormData();
      for (const file of incoming) body.append("files", file);
      const result = await readApi<FileList>("/api/files", { method: "POST", body });
      setFiles(result.files);
      setLimit(result.limit);
      const added = result.added ?? [];
      setSelectedIds(added.map((file) => file.id));
      const rejected = (result.rejected ?? []).map((item) => `${item.name}: ${item.reason}`);
      setNotice(rejected.length > 0 ? rejected.join(" ") : null);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Upload failed.");
    } finally {
      setBusy(null);
    }
  }

  async function matchSelected() {
    if (selectedIds.length === 0) return;
    setBusy("Matching the selected documents…");
    setNotice(null);
    try {
      const view = await readApi<RunView>("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_ids: selectedIds }),
      });
      await refreshLists();
      setActiveId(view.id);
      setActive(view);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "The match could not be started.");
    } finally {
      setBusy(null);
    }
  }

  function replaceRun(view: RunView) {
    setActive(view);
    setRuns((current) =>
      current.map((run) =>
        run.id === view.id
          ? {
              ...run,
              status: view.status,
              routing: view.routing,
              confidence: view.confidence,
              exception_codes: view.exception_codes,
              primary_exception: view.primary_exception,
              awaiting_approval: view.awaiting_approval,
              po_number: view.match?.po_number ?? run.po_number,
              invoice_number: view.match?.invoice_number ?? run.invoice_number,
              vendor_name: view.match?.vendor_name ?? run.vendor_name,
              invoice_total: view.match?.invoice_total ?? run.invoice_total,
              currency: view.match?.currency ?? run.currency,
            }
          : run,
      ),
    );
  }

  const linkedRuns = linkFilesToRuns(files, runs, intake);
  const linkedRunIds = new Set([...linkedRuns.values()].map((run) => run.id));
  const unlinkedRuns = runs.filter((run) => !linkedRunIds.has(run.id));

  const cleared = runs.filter((run) => run.routing === "auto_clear").length;
  const flagged = runs.filter((run) => run.routing === "flag").length;
  const rejected = runs.filter((run) => run.routing === "reject").length;
  const saved = minutesSaved(runs);
  const visibleFiles = files.filter((file) => matchesQueue(linkedRuns.get(file.id) ?? null, queueFilter));
  const visibleUnlinked = unlinkedRuns.filter((run) => matchesQueue(run, queueFilter));

  function chooseFilter(next: QueueFilter) {
    setQueueFilter((current) => (current === next ? "all" : next));
  }

  return (
    <div
      className="relative mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8"
      onDragOver={(event) => {
        event.preventDefault();
        if (!dragging) setDragging(true);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void upload(Array.from(event.dataTransfer.files));
      }}
    >
      {dragging ? (
        <div className="pointer-events-none absolute inset-3 z-20 flex items-center justify-center rounded-3xl border-2 border-dashed border-accent bg-stamp/80">
          <p className="font-serif text-2xl text-ink">Drop documents to read them</p>
        </div>
      ) : null}
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-2xl">
          <h1 className="font-serif text-4xl tracking-tight text-ink sm:text-5xl">DocProcessor</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            Upload a purchase order, invoice, and goods receipt. A layout reader fills the fields. A local
            Ollama model reads the page only when a required field is still missing. The match stays in code.
            A clean match auto-clears. A commercial exception waits for review. An exact duplicate, a missing document, or an unreadable file is rejected. A person approves every draft.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void clearDesk()}
            disabled={busy !== null || !canClear}
            className="rounded-full border border-line bg-card px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
          >
            Clear
          </button>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy !== null || files.length >= limit}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
          >
            Upload
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            onChange={(event) => {
              const picked = Array.from(event.target.files ?? []);
              event.target.value = "";
              void upload(picked);
            }}
          />
        </div>
      </header>

      {offline ? (
        <p role="alert" className="rounded-xl border border-danger/20 bg-danger-wash px-3 py-2 text-sm text-danger">
          The API on port 8000 is not responding. From the backend folder, run{" "}
          <code className="font-mono">uv run uvicorn app.main:app --reload --port 8000</code>.
        </p>
      ) : null}
      {notice ? (
        <p role="alert" className="rounded-xl border border-danger/20 bg-danger-wash px-3 py-2 text-sm text-danger">
          {notice}
        </p>
      ) : null}
      {busy ? <p className="text-sm text-muted">{busy}</p> : null}
      {intake?.status === "running" && intake.total > 0 ? (
        <div>
          <div className="h-1.5 overflow-hidden rounded-full bg-line" aria-hidden>
            <div
              className="h-full rounded-full bg-accent transition-[width]"
              style={{ width: `${Math.min(100, (intake.processed / intake.total) * 100)}%` }}
            />
          </div>
          <p className="mt-2 text-sm text-muted">{intake.message}</p>
        </div>
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Documents on file" value={String(files.length)} detail={`of ${limit}`} />
        <Stat
          label="Cases"
          value={String(runs.length)}
          detail={loadingList ? "Loading…" : queueFilter === "all" ? "Showing every case" : "Filtered"}
          pressed={queueFilter === "all"}
          onClick={() => setQueueFilter("all")}
        />
        <Stat
          label="Auto-cleared"
          value={String(cleared)}
          detail="Click to show"
          pressed={queueFilter === "auto_clear"}
          onClick={() => chooseFilter("auto_clear")}
        />
        <Stat
          label="Needs review"
          value={String(flagged)}
          detail="Click to show"
          pressed={queueFilter === "flag"}
          onClick={() => chooseFilter("flag")}
        />
        <Stat
          label="Rejected"
          value={String(rejected)}
          detail="Click to show"
          pressed={queueFilter === "reject"}
          onClick={() => chooseFilter("reject")}
        />
      </section>

      <section className="overflow-hidden rounded-2xl border border-line bg-card">
        <div className="h-0.5 bg-accent" />
        <div className="px-4 py-4 sm:px-5">
          <p className="text-xs tracking-[0.16em] text-muted uppercase">Potential AP time saved</p>
          <p className="mt-1 font-serif text-3xl text-ink">{runs.length === 0 ? "—" : formatHours(saved)}</p>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
            Assumes 25 minutes to chase one case by hand, 2 minutes to confirm an auto-clear, 8 minutes to review a
            prepared draft, and 20 minutes when the set is rejected for manual handling.
          </p>
        </div>
      </section>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(16rem,0.85fr)_minmax(0,1.25fr)]">
        <section className="flex flex-col gap-4">
          <div className="overflow-hidden rounded-2xl border border-line bg-card">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <h2 className="text-sm font-medium text-ink">Cases</h2>
              <span className="text-xs text-muted">
                {loadingList ? "Loading…" : files.length > 0 ? `${files.length}` : `${runs.length}`}
              </span>
            </div>
            {files.length === 0 && runs.length === 0 ? (
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="w-full px-4 py-8 text-left text-sm leading-6 text-muted"
              >
                Drop a purchase order, invoice, and goods receipt here, or click to choose files. Matching starts in
                the background.
              </button>
            ) : visibleFiles.length === 0 && visibleUnlinked.length === 0 ? (
              <p className="px-4 py-8 text-sm leading-6 text-muted">No cases in this view. Click the same total again to show every case.</p>
            ) : (
              <ul className="divide-y divide-line">
                {visibleFiles.map((file) => {
                  const run = linkedRuns.get(file.id) ?? null;
                  const reading = intake?.status === "running" && intake.current === file.name;
                  const active = activeFileId ? file.id === activeFileId : run?.id === activeId;
                  return (
                    <li key={file.id} className={active ? "bg-stamp" : "bg-card"}>
                      <button
                        type="button"
                        onClick={() => {
                          setActiveFileId(file.id);
                          if (run) void openCase(run.id);
                        }}
                        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
                        aria-pressed={active}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-ink">{file.name}</span>
                          <span className="mt-0.5 block truncate text-xs text-muted">
                            {run
                              ? `${run.vendor_name ?? "Vendor unreadable"}${run.invoice_number ? ` · ${run.invoice_number}` : ""}${run.awaiting_approval ? " · waiting" : ""}`
                              : reading
                                ? intake?.message
                                : "Uploaded"}
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          <span className={`block text-xs ${tone(run?.routing ?? null)}`}>
                            {run ? routingLabel(run.routing) : reading ? "Reading" : "Uploaded"}
                          </span>
                          <span className="mt-0.5 block text-xs text-muted">
                            {run ? formatPercent(run.confidence) : ""}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
                {visibleUnlinked.map((run) => {
                  const active = run.id === activeId && activeFileId === null;
                  return (
                    <li key={run.id} className={active ? "bg-stamp" : "bg-card"}>
                      <button
                        type="button"
                        onClick={() => {
                          setActiveFileId(null);
                          void openCase(run.id);
                        }}
                        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
                        aria-pressed={active}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-ink">
                            {caseTitle(run.label, run.invoice_number)}
                          </span>
                          <span className="mt-0.5 block truncate text-xs text-muted">
                            {run.vendor_name ?? "Vendor unreadable"}
                            {run.invoice_number ? ` · ${run.invoice_number}` : ""}
                            {run.awaiting_approval ? " · waiting" : ""}
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          <span className={`block text-xs ${tone(run.routing)}`}>{routingLabel(run.routing)}</span>
                          <span className="mt-0.5 block text-xs text-muted">{formatPercent(run.confidence)}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {files.length > 0 ? (
            <div className="rounded-2xl border border-line bg-card">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <h2 className="text-sm font-medium text-ink">Match a selection</h2>
                <button
                  type="button"
                  onClick={() => void matchSelected()}
                  disabled={busy !== null || selectedIds.length === 0}
                  className="rounded-full bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
                >
                  Run match
                </button>
              </div>
              <ul className="max-h-64 divide-y divide-line overflow-auto">
                {files.map((file) => {
                  const checked = selectedIds.includes(file.id);
                  return (
                    <li key={file.id} className="flex items-center gap-3 px-4 py-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {
                          setSelectedIds((current) =>
                            current.includes(file.id)
                              ? current.filter((id) => id !== file.id)
                              : [...current, file.id],
                          );
                          setActive(null);
                          setActiveId(null);
                          setActiveFileId(null);
                        }}
                        aria-label={file.name}
                      />
                      <span className="min-w-0 flex-1 truncate text-sm text-ink">{file.name}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </section>

        <section className="rounded-2xl border border-line bg-paper/40 p-4 sm:p-5 lg:sticky lg:top-6">
          <CaseReview
            key={active?.id ?? "empty"}
            run={active}
            loading={loadingCase}
            fileSelected={selectedIds.length > 0}
            hasFiles={files.length > 0}
            onChange={replaceRun}
          />
        </section>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  detail,
  pressed,
  onClick,
}: {
  label: string;
  value: string;
  detail?: string;
  pressed?: boolean;
  onClick?: () => void;
}) {
  const body = (
    <>
      <div className="h-0.5 bg-accent" />
      <div className="px-4 py-3 text-left">
        <p className="text-xs text-muted">{label}</p>
        <p className="mt-1 font-serif text-3xl text-ink">{value}</p>
        {detail ? <p className="text-xs text-muted">{detail}</p> : null}
      </div>
    </>
  );
  if (!onClick) {
    return <div className="overflow-hidden rounded-2xl border border-line bg-card">{body}</div>;
  }
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={pressed}
      className={`overflow-hidden rounded-2xl border text-left transition-colors ${
        pressed ? "border-accent bg-stamp" : "border-line bg-card hover:border-accent"
      }`}
    >
      {body}
    </button>
  );
}

type QueueFilter = "all" | "auto_clear" | "flag" | "reject";

function matchesQueue(run: RunSummary | null, filter: QueueFilter): boolean {
  if (filter === "all") return true;
  return run?.routing === filter;
}

function linkFilesToRuns(
  files: StoredFile[],
  runs: RunSummary[],
  intake: IntakeStatus | null,
): Map<string, RunSummary> {
  const linked = new Map<string, RunSummary>();
  for (const run of runs) {
    for (const id of run.file_ids ?? []) linked.set(id, run);
  }
  if (intake?.run_id) {
    const run = runs.find((item) => item.id === intake.run_id);
    if (run) {
      for (const id of intake.file_ids ?? []) {
        if (!linked.has(id)) linked.set(id, run);
      }
    }
  }
  const used = new Set([...linked.values()].map((run) => run.id));
  const openRuns = runs.filter((run) => !used.has(run.id));
  const openFiles = files.filter((file) => !linked.has(file.id));
  if (
    intake?.status !== "running" &&
    openRuns.length === 1 &&
    openFiles.length === openRuns[0].file_count
  ) {
    for (const file of openFiles) linked.set(file.id, openRuns[0]);
  }
  return linked;
}

function tone(routing: RunSummary["routing"]): string {
  if (routing === "auto_clear") return "text-accent";
  if (routing === "flag") return "text-warn";
  if (routing === "reject") return "text-danger";
  return "text-muted";
}
