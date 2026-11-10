/**
 * Everything the frontend knows about the backend lives in this file.
 * UI components call these functions and never use fetch() directly.
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// ---------- types (the shape of what the backend sends) ----------

export type Status = "queued" | "processing" | "completed" | "needs_review" | "failed";

export interface LineItem {
  description: string | null;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
}

export interface InvoiceData {
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  supplier_name: string | null;
  customer_name: string | null;
  currency: string | null;
  subtotal: number | null;
  tax: number | null;
  total: number | null;
  line_items: LineItem[];
  uncertain_fields: string[];
}

export interface Issue {
  field: string;
  code: string;
  severity: "error" | "warning";
  message: string;
}

export interface DocumentSummary {
  id: number;
  file_name: string;
  file_type: string | null;
  status: Status;
  error_message: string | null;
  page_count: number | null;
  ocr_confidence: number | null;
  needs_review: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentEvent {
  event: string;
  detail: string | null;
  created_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  extraction: {
    ai_data: InvoiceData;
    corrected_data: InvoiceData | null;
    final_data: InvoiceData;
    extracted_text: string | null;
  } | null;
  issues: Issue[];
  events: DocumentEvent[];
}

export interface UploadResult {
  accepted: { id: number; file_name: string; status: Status }[];
  rejected: { file_name: string; reason: string }[];
}

// ---------- one place that talks to the network ----------

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running?", 0);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    let detail: unknown = undefined;
    try {
      const body = await response.json();
      detail = body.detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object" && "message" in detail) {
        message = String((detail as { message: unknown }).message);
      } else if (Array.isArray(detail)) {
        message = detail.map((d: { msg?: string }) => d.msg ?? "invalid value").join("; ");
      }
    } catch {
      // the error body was not JSON; keep the default message
    }
    throw new ApiError(message, response.status, detail);
  }
  return (await response.json()) as T;
}

// ---------- the functions the UI uses ----------

export async function uploadDocuments(files: File[]): Promise<UploadResult> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  try {
    // no Content-Type header here: the browser sets it, including the multipart boundary
    return await request<UploadResult>("/documents", { method: "POST", body: form });
  } catch (error) {
    // when every file is refused the backend answers 400 with the reasons: show them
    if (error instanceof ApiError && error.status === 400) {
      const detail = error.detail as { rejected?: UploadResult["rejected"] } | undefined;
      if (detail && Array.isArray(detail.rejected)) {
        return { accepted: [], rejected: detail.rejected };
      }
    }
    throw error;
  }
}

export function listDocuments(status?: Status): Promise<DocumentSummary[]> {
  const query = status ? `?status=${status}` : "";
  return request<DocumentSummary[]>(`/documents${query}`);
}

export function getDocument(id: number): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${id}`);
}

export function correctDocument(id: number, data: InvoiceData): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${id}/correction`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function reprocessDocument(id: number): Promise<{ id: number; status: Status }> {
  return request(`/documents/${id}/reprocess`, { method: "POST" });
}

export function searchDocuments(q: string): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>(`/search?q=${encodeURIComponent(q)}`);
}

export async function semanticSearchDocuments(q: string): Promise<DocumentSummary[]> {
  const found = await request<{ results: { document_id: number; score: number }[] }>(
    `/search/semantic?q=${encodeURIComponent(q)}`
  );
  // the backend returns ids + scores; load each document so the UI can show its normal card
  const documents = await Promise.all(found.results.map((r) => getDocument(r.document_id)));
  return documents;
}