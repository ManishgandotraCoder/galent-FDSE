/** Shapes returned by the Python API. Display helpers live in `lib/format.ts`. */

export type Routing = "auto_clear" | "flag" | "reject";

export type MatchCheck = {
  label: string;
  passed: boolean;
};

export type RuleResult = {
  rule: string;
  status: "PASS" | "FAIL" | "WARN";
  expected: string | null;
  actual: string | null;
  severity: "HIGH" | "MEDIUM" | "LOW";
  reason: string;
};

export type Scorecard = {
  completeness: number;
  extraction: number;
  validation: number;
  matching: number;
  routing_score: number;
};

export type ExceptionItem = {
  type: string;
  severity: "high" | "medium";
  message: string;
};

export type LineComparison = {
  key: string;
  description: string;
  po_quantity: string | number | null;
  invoice_quantity: string | number | null;
  received_quantity: string | number | null;
  po_unit_price: string | number | null;
  invoice_unit_price: string | number | null;
  status: "matched" | "exception";
  notes: string[];
};

export type ThreeWayMatch = {
  status: string;
  po_number: string | null;
  invoice_number: string | null;
  grn_number: string | null;
  vendor_name: string | null;
  currency: string | null;
  po_total: string | number | null;
  invoice_total: string | number | null;
  grn_total: string | number | null;
  exceptions: string[];
  lines: LineComparison[];
  checks: MatchCheck[];
  rules?: RuleResult[];
  summary: string;
};

export type EmailDraft = {
  to_role: "vendor" | "approver";
  subject: string;
  body: string;
  requires_approval: boolean;
};

export type RunSummary = {
  id: string;
  label: string | null;
  status: string;
  routing: Routing | null;
  confidence: number | null;
  exception_codes: string[];
  primary_exception: string | null;
  awaiting_approval: boolean;
  po_number: string | null;
  invoice_number: string | null;
  vendor_name: string | null;
  invoice_total: string | number | null;
  currency: string | null;
  file_count: number;
  file_ids?: string[];
  source_names?: string[];
  latency_ms: number | null;
};

export type RunView = {
  id: string;
  status: string;
  routing: Routing | null;
  confidence: number | null;
  scores?: Scorecard | null;
  risk?: "none" | "soft" | "hard" | null;
  exception_codes: string[];
  primary_exception: string | null;
  exceptions: ExceptionItem[];
  validation_issues: { file_id: string; code: string; message: string }[];
  match: ThreeWayMatch | null;
  email_draft: EmailDraft | null;
  extractions: {
    file_id: string;
    source_name: string | null;
    document_type: string | null;
    confidence: number;
    extractor?: string | null;
    warnings?: string[];
  }[];
  awaiting_approval: boolean;
  approval: { approved: boolean; note: string | null } | null;
};

export type StoredFile = {
  id: string;
  name: string;
  size: number;
  type: string;
  uploadedAt: string;
};

export type IntakeStatus = {
  status: "idle" | "running" | "done" | "failed";
  uploaded: number;
  total: number;
  processed: number;
  accepted: number;
  rejected: number;
  current: string | null;
  message: string;
  run_id: string | null;
  file_ids?: string[];
};

export type FileList = {
  files: StoredFile[];
  limit: number;
  added?: StoredFile[];
  rejected?: { name: string; reason: string }[];
  error?: string;
};

export type EvalReport = {
  documents_processed: number;
  field_accuracy: number | null;
  exception_precision: number | null;
  exception_recall: number | null;
  average_latency_ms: number;
  p95_latency_ms: number;
  average_tokens?: number;
  variant_cases?: number;
  false_auto_clear_rate?: number | null;
  auto_clear_precision?: number | null;
  auto_clear_recall?: number | null;
  false_rejection_rate?: number | null;
  human_review_rate?: number | null;
  auto_clear_confidence: number;
  flag_confidence: number;
  documents: {
    document_id: string;
    presentation: string;
    language: string;
    field_accuracy: number | null;
    field_correct: number;
    field_total: number;
    confidence: number;
    latency_ms: number;
    input_tokens?: number;
    output_tokens?: number;
    tokens?: number;
    expected_validation: string[];
    predicted_validation: string[];
    warnings: string[];
  }[];
  bundles: {
    bundle_id: string;
    expected_status: string;
    predicted_status: string;
    expected_exceptions: string[];
    predicted_exceptions: string[];
  }[];
};
