import type { Routing } from "@/lib/api/types";

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} sec`;
}

export function formatMoney(amount: string | number | null | undefined, currency: string | null): string {
  if (amount == null || amount === "") return "—";
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return String(amount);
  const code = currency && currency.length === 3 ? currency : "INR";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${code} ${value.toFixed(2)}`;
  }
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatCode(code: string | null | undefined): string {
  if (!code) return "—";
  return code.replaceAll("_", " ");
}

export function caseTitle(label: string | null, invoice: string | null): string {
  if (label) {
    return label
      .split(/[-_]/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }
  if (invoice) return `Invoice ${invoice}`;
  return "Untitled case";
}

export function routingLabel(routing: Routing | null): string {
  if (routing === "auto_clear") return "Auto-cleared";
  if (routing === "flag") return "Needs review";
  if (routing === "reject") return "Rejected";
  return "Pending";
}
