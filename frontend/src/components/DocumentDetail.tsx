"use client";

import { useCallback, useEffect, useState } from "react";
import {
  correctDocument,
  getDocument,
  reprocessDocument,
  type DocumentDetail as DocumentDetailData,
  type InvoiceData,
  type Issue,
} from "@/lib/api";
import { StatusBadge } from "./DocumentList";

const TEXT_FIELDS = [
  ["invoice_number", "Invoice number"],
  ["invoice_date", "Invoice date (YYYY-MM-DD)"],
  ["due_date", "Due date (YYYY-MM-DD)"],
  ["supplier_name", "Supplier"],
  ["customer_name", "Customer"],
  ["currency", "Currency (e.g. USD)"],
] as const;

const NUMBER_FIELDS = [
  ["subtotal", "Subtotal"],
  ["tax", "Tax"],
  ["total", "Total"],
] as const;

type TextKey = (typeof TEXT_FIELDS)[number][0];
type NumberKey = (typeof NUMBER_FIELDS)[number][0];
type FieldKey = TextKey | NumberKey;

interface LineForm {
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
}
type FormState = Record<FieldKey, string> & { line_items: LineForm[] };

// The form keeps everything as text so typing "12." does not get rewritten while you type.
const str = (v: string | number | null | undefined) => (v === null || v === undefined ? "" : String(v));

function toForm(d: InvoiceData): FormState {
  return {
    invoice_number: str(d.invoice_number),
    invoice_date: str(d.invoice_date),
    due_date: str(d.due_date),
    supplier_name: str(d.supplier_name),
    customer_name: str(d.customer_name),
    currency: str(d.currency),
    subtotal: str(d.subtotal),
    tax: str(d.tax),
    total: str(d.total),
    line_items: d.line_items.map((li) => ({
      description: str(li.description),
      quantity: str(li.quantity),
      unit_price: str(li.unit_price),
      amount: str(li.amount),
    })),
  };
}

function textOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function parseNumber(value: string, label: string): number | null {
  const cleaned = value.trim().replace(/,/g, "");
  if (cleaned === "") return null;
  const number = Number(cleaned);
  if (!Number.isFinite(number)) throw new Error(`${label} must be a number.`);
  return number;
}

function toInvoice(form: FormState): InvoiceData {
  const rows = form.line_items.filter((li) => Object.values(li).some((v) => v.trim() !== ""));
  return {
    invoice_number: textOrNull(form.invoice_number),
    invoice_date: textOrNull(form.invoice_date),
    due_date: textOrNull(form.due_date),
    supplier_name: textOrNull(form.supplier_name),
    customer_name: textOrNull(form.customer_name),
    currency: textOrNull(form.currency),
    subtotal: parseNumber(form.subtotal, "Subtotal"),
    tax: parseNumber(form.tax, "Tax"),
    total: parseNumber(form.total, "Total"),
    line_items: rows.map((li, i) => ({
      description: textOrNull(li.description),
      quantity: parseNumber(li.quantity, `Line ${i + 1} quantity`),
      unit_price: parseNumber(li.unit_price, `Line ${i + 1} unit price`),
      amount: parseNumber(li.amount, `Line ${i + 1} amount`),
    })),
    uncertain_fields: [],
  };
}

function borderFor(issues: Issue[], uncertain: boolean): string {
  if (issues.some((i) => i.severity === "error")) return "border-red-400 dark:border-red-600";
  if (issues.length > 0 || uncertain) return "border-amber-400 dark:border-amber-600";
  return "border-neutral-300 dark:border-neutral-700";
}

function Field(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  issues: Issue[];
  uncertain: boolean;
  aiValue?: string;
}) {
  const { label, value, onChange, issues, uncertain, aiValue } = props;
  return (
    <label className="block text-sm">
      <span className="font-medium">{label}</span>
      {uncertain && <span className="ml-2 text-xs text-amber-700 dark:text-amber-400">AI was not sure</span>}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1 w-full rounded-md border bg-transparent px-3 py-2 ${borderFor(issues, uncertain)}`}
      />
      {issues.map((issue, index) => (
        <span
          key={index}
          className={`mt-1 block text-xs ${
            issue.severity === "error" ? "text-red-600 dark:text-red-400" : "text-amber-700 dark:text-amber-400"
          }`}
        >
          {issue.message}
        </span>
      ))}
      {aiValue !== undefined && (
        <span className="mt-1 block text-xs text-neutral-500">
          AI originally read: {aiValue === "" ? "(empty)" : aiValue}
        </span>
      )}
    </label>
  );
}

interface Props {
  documentId: number;
  onChanged: () => void;
}

export default function DocumentDetail({ documentId, onChanged }: Props) {
  const [doc, setDoc] = useState<DocumentDetailData | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setDoc(await getDocument(documentId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the document.");
    }
  }, [documentId]);

  // a different document was selected: start fresh
  useEffect(() => {
    setDoc(null);
    setForm(null);
    setNotice(null);
    void load();
  }, [load]);

  // every time fresh data arrives, fill the form from the final values (human correction wins)
  useEffect(() => {
    setForm(doc?.extraction ? toForm(doc.extraction.final_data) : null);
  }, [doc]);

  // refresh while the document is still being processed
  const busy = doc?.status === "queued" || doc?.status === "processing";
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [busy, load]);

  async function save() {
    if (!form) return;
    setError(null);
    setNotice(null);
    let payload: InvoiceData;
    try {
      payload = toInvoice(form);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Please check the values.");
      return;
    }
    setSaving(true);
    try {
      const updated = await correctDocument(documentId, payload);
      setNotice(
        updated.status === "completed"
          ? "Saved. All checks passed."
          : "Saved. Some checks still need attention.",
      );
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  async function retry() {
    try {
      await reprocessDocument(documentId);
      setNotice(null);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not retry.");
    }
  }

  if (!doc) {
    return (
      <section className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : <p className="text-sm text-neutral-500">Loading...</p>}
      </section>
    );
  }

  const extraction = doc.extraction;
  const fieldIssues = (name: string) =>
    doc.issues.filter((i) => i.field === name && i.code !== "uncertain_field");
  const isUncertain = (name: string) => extraction?.final_data.uncertain_fields.includes(name) ?? false;
  const aiHint = (key: FieldKey): string | undefined => {
    if (!extraction?.corrected_data) return undefined;
    const original = str(extraction.ai_data[key]);
    return original !== str(extraction.corrected_data[key]) ? original : undefined;
  };

  function setField(key: FieldKey, value: string) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
  }
  function setLine(index: number, key: keyof LineForm, value: string) {
    setForm((current) =>
      current
        ? { ...current, line_items: current.line_items.map((li, i) => (i === index ? { ...li, [key]: value } : li)) }
        : current,
    );
  }

  return (
    <section aria-labelledby="detail-title" className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="detail-title" className="truncate text-lg font-semibold">
            {doc.file_name}
          </h2>
          <p className="text-xs text-neutral-500">
            #{doc.id} · {doc.file_type ?? "unknown"} · {doc.page_count ?? "?"} page(s)
            {doc.ocr_confidence !== null && ` · OCR confidence ${Math.round(doc.ocr_confidence)}%`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={doc.status} />
          {!busy && (
            <button onClick={() => void retry()} className="rounded-md border border-neutral-300 px-2 py-1 text-xs hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800">
              Reprocess
            </button>
          )}
        </div>
      </div>

      <div aria-live="polite" className="mt-3 space-y-2 text-sm">
        {error && <p className="rounded-md bg-red-50 p-3 text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>}
        {notice && <p className="rounded-md bg-green-50 p-3 text-green-800 dark:bg-green-950 dark:text-green-300">{notice}</p>}
        {busy && <p className="rounded-md bg-blue-50 p-3 text-blue-800 dark:bg-blue-950 dark:text-blue-300">Processing... this page updates by itself.</p>}
        {doc.status === "failed" && (
          <p className="rounded-md bg-red-50 p-3 text-red-700 dark:bg-red-950 dark:text-red-300">
            Processing failed: {doc.error_message ?? "unknown reason"}
          </p>
        )}
      </div>

      {doc.issues.length > 0 && (
        <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950">
          <p className="font-medium">
            {doc.issues.length} thing{doc.issues.length > 1 ? "s" : ""} to review
          </p>
          <ul className="mt-1 space-y-1">
            {doc.issues.map((issue, index) => (
              <li key={index} className={issue.severity === "error" ? "text-red-700 dark:text-red-300" : "text-amber-900 dark:text-amber-300"}>
                <span className="font-medium">{issue.severity === "error" ? "Error" : "Warning"}</span> ({issue.field}): {issue.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {form && (
        <form
          className="mt-5 space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            {TEXT_FIELDS.map(([key, label]) => (
              <Field key={key} label={label} value={form[key]} onChange={(v) => setField(key, v)} issues={fieldIssues(key)} uncertain={isUncertain(key)} aiValue={aiHint(key)} />
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {NUMBER_FIELDS.map(([key, label]) => (
              <Field key={key} label={label} value={form[key]} onChange={(v) => setField(key, v)} issues={fieldIssues(key)} uncertain={isUncertain(key)} aiValue={aiHint(key)} />
            ))}
          </div>

          <div>
            <h3 className="text-sm font-semibold">Line items</h3>
            {form.line_items.length === 0 && <p className="mt-1 text-xs text-neutral-500">No line items were found.</p>}
            <div className="mt-2 space-y-2">
              {form.line_items.map((li, index) => {
                const rowIssues = doc.issues.filter((i) => i.field.startsWith(`line_items[${index + 1}]`));
                return (
                  <div key={index}>
                    <div className="grid grid-cols-[2fr_1fr_1fr_1fr_auto] gap-2">
                      {(["description", "quantity", "unit_price", "amount"] as const).map((key) => (
                        <input
                          key={key}
                          aria-label={`Line ${index + 1} ${key.replace("_", " ")}`}
                          placeholder={key.replace("_", " ")}
                          value={li[key]}
                          onChange={(e) => setLine(index, key, e.target.value)}
                          className={`w-full rounded-md border bg-transparent px-2 py-1.5 text-sm ${borderFor(rowIssues, false)}`}
                        />
                      ))}
                      <button
                        type="button"
                        aria-label={`Remove line ${index + 1}`}
                        onClick={() => setForm((c) => (c ? { ...c, line_items: c.line_items.filter((_, i) => i !== index) } : c))}
                        className="rounded-md border border-neutral-300 px-2 text-sm hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
                      >
                        x
                      </button>
                    </div>
                    {rowIssues.map((issue, i) => (
                      <p key={i} className="mt-1 text-xs text-red-600 dark:text-red-400">{issue.message}</p>
                    ))}
                  </div>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => setForm((c) => (c ? { ...c, line_items: [...c.line_items, { description: "", quantity: "", unit_price: "", amount: "" }] } : c))}
              className="mt-2 rounded-md border border-neutral-300 px-3 py-1 text-xs hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              Add line
            </button>
          </div>

          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? "Saving..." : "Save correction and re-check"}
          </button>
        </form>
      )}

      {extraction?.extracted_text && (
        <details className="mt-5 text-sm">
          <summary className="cursor-pointer font-medium">Text read from the document</summary>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-neutral-100 p-3 text-xs dark:bg-neutral-800">{extraction.extracted_text}</pre>
        </details>
      )}

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer font-medium">History ({doc.events?.length ?? 0})</summary>
        <ul className="mt-2 space-y-1 text-xs text-neutral-600 dark:text-neutral-400">
          {(doc.events ?? []).map((event, index) => (
            <li key={index}>
              {new Date(event.created_at + "Z").toLocaleString()} · {event.event}
              {event.detail ? ` (${event.detail})` : ""}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}