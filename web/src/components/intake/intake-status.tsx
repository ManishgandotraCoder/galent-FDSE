"use client";

import { useEffect, useState } from "react";

import { readApi } from "@/lib/api/client";
import type { IntakeStatus } from "@/lib/api/types";

const EMPTY: IntakeStatus = {
  status: "idle",
  uploaded: 0,
  total: 0,
  processed: 0,
  accepted: 0,
  rejected: 0,
  current: null,
  message: "",
  run_id: null,
};

export function IntakeStatusButton() {
  const [intake, setIntake] = useState<IntakeStatus>(EMPTY);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const next = await readApi<IntakeStatus>("/api/intake");
        if (!cancelled) setIntake(next);
      } catch {
        if (!cancelled) setIntake(EMPTY);
      }
    }

    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!intake.message) return null;

  const running = intake.status === "running";
  const failed = intake.status === "failed";

  return (
    <button
      type="button"
      disabled
      aria-live="polite"
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
        failed
          ? "border-danger/30 bg-danger-wash text-danger"
          : "border-line bg-paper text-ink"
      }`}
    >
      {running ? (
        <span
          className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent"
          aria-hidden
        />
      ) : null}
      {intake.message}
    </button>
  );
}
