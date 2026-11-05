"use client";

import { useCallback, useEffect, useState } from "react";
import { listDocuments, reprocessDocument, type DocumentSummary, type Status } from "@/lib/api";

const STATUS_STYLES: Record<Status, { label: string; classes: string }> = {
  queued: { label: "Queued", classes: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300" },
  processing: { label: "Processing", classes: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300" },
  completed: { label: "Completed", classes: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300" },
  needs_review: { label: "Needs review", classes: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300" },
  failed: { label: "Failed", classes: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300" },
};

const FILTERS: { value: Status | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "needs_review", label: "Needs review" },
  { value: "failed", label: "Failed" },
  { value: "completed", label: "Completed" },
  { value: "processing", label: "In progress" },
];

const POLL_MS = 2000;

export function StatusBadge({ status }: { status: Status }) {
  const style = STATUS_STYLES[status];
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${style.classes}`}>
      {style.label}
    </span>
  );
}

interface Props {
  refreshKey: number;
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export default function DocumentList({ refreshKey, selectedId, onSelect }: Props) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [filter, setFilter] = useState<Status | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      // "processing" also covers queued documents, so the filter shows everything still running
      const status = filter === "all" ? undefined : filter === "processing" ? undefined : filter;
      const data = await listDocuments(status);
      setDocuments(filter === "processing" ? data.filter((d) => d.status === "queued" || d.status === "processing") : data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load documents.");
    } finally {
      setLoaded(true);
    }
  }, [filter]);

  // load on first show, when the filter changes, and when the page says something was uploaded
  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // keep refreshing only while something is still being processed
  const busy = documents.some((d) => d.status === "queued" || d.status === "processing");
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [busy, load]);

  async function retry(id: number) {
    try {
      await reprocessDocument(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not retry.");
    }
  }

  return (
    <section aria-labelledby="list-title" className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="list-title" className="text-lg font-semibold">
          Documents
          {busy && <span className="ml-2 text-xs font-normal text-blue-600 dark:text-blue-400">updating live...</span>}
        </h2>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              onClick={() => setFilter(item.value)}
              aria-pressed={filter === item.value}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                filter === item.value
                  ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"
                  : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-300"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>
      )}

      {!loaded ? (
        <p className="mt-4 text-sm text-neutral-500">Loading...</p>
      ) : documents.length === 0 ? (
        <p className="mt-4 text-sm text-neutral-500">No documents here yet. Upload one to get started.</p>
      ) : (
        <ul className="mt-4 divide-y divide-neutral-200 dark:divide-neutral-800">
          {documents.map((doc) => (
            <li key={doc.id}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSelect(doc.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(doc.id);
                  }
                }}
                aria-current={selectedId === doc.id}
                className={`flex cursor-pointer items-center justify-between gap-3 px-2 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-800 ${
                  selectedId === doc.id ? "bg-blue-50 dark:bg-blue-950" : ""
                }`}
              >
                <div className="min-w-0">
                  <p className="truncate font-medium">{doc.file_name}</p>
                  <p className="text-xs text-neutral-500">
                    #{doc.id} · {doc.file_type ?? "unknown"} · {new Date(doc.created_at + "Z").toLocaleString()}
                  </p>
                  {doc.status === "failed" && doc.error_message && (
                    <p className="mt-1 truncate text-xs text-red-600 dark:text-red-400">{doc.error_message}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <StatusBadge status={doc.status} />
                  {(doc.status === "failed" || doc.status === "needs_review") && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        void retry(doc.id);
                      }}
                      className="rounded-md border border-neutral-300 px-2 py-1 text-xs hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
                    >
                      Retry
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}