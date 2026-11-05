"use client";

import { useState } from "react";
import DocumentDetail from "@/components/DocumentDetail";
import DocumentList, { StatusBadge } from "@/components/DocumentList";
import UploadPanel from "@/components/UploadPanel";
import { searchDocuments, type DocumentSummary } from "@/lib/api";

function SearchPanel({ onSelect }: { onSelect: (id: number) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DocumentSummary[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    const q = query.trim();
    setError(null);
    if (!q) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      setResults(await searchDocuments(q));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed.");
    } finally {
      setSearching(false);
    }
  }

  return (
    <section aria-labelledby="search-title" className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <h2 id="search-title" className="text-lg font-semibold">
        Search
      </h2>
      <p className="mt-1 text-sm text-neutral-500">Find documents by file name, supplier, invoice number or any text inside them.</p>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. Sunrise, 00427, chair"
          aria-label="Search documents"
          className="w-full rounded-md border border-neutral-300 bg-transparent px-3 py-2 text-sm dark:border-neutral-700"
        />
        <button type="submit" disabled={searching} className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-neutral-100 dark:text-neutral-900">
          {searching ? "..." : "Search"}
        </button>
      </form>

      <div aria-live="polite" className="mt-3 text-sm">
        {error && <p className="rounded-md bg-red-50 p-3 text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>}
        {results && results.length === 0 && <p className="text-neutral-500">No documents matched.</p>}
        {results && results.length > 0 && (
          <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {results.map((doc) => (
              <li key={doc.id}>
                <button onClick={() => onSelect(doc.id)} className="flex w-full items-center justify-between gap-3 px-2 py-2 text-left hover:bg-neutral-50 dark:hover:bg-neutral-800">
                  <span className="truncate">
                    {doc.file_name} <span className="text-xs text-neutral-500">#{doc.id}</span>
                  </span>
                  <StatusBadge status={doc.status} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {results && (
          <button onClick={() => { setResults(null); setQuery(""); }} className="mt-2 text-xs text-blue-600 underline dark:text-blue-400">
            Clear search
          </button>
        )}
      </div>
    </section>
  );
}

export default function Home() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const refresh = () => setRefreshKey((k) => k + 1);

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <header>
        <h1 className="text-2xl font-bold">Document Intelligence System</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Upload invoices, let AI extract the data, review what the checks found, and correct anything that is wrong.
        </p>
      </header>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <UploadPanel onUploaded={refresh} />
          <SearchPanel onSelect={setSelectedId} />
          <DocumentList refreshKey={refreshKey} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        <div>
          {selectedId !== null ? (
            <DocumentDetail key={selectedId} documentId={selectedId} onChanged={refresh} />
          ) : (
            <section className="rounded-xl border border-dashed border-neutral-300 p-10 text-center text-sm text-neutral-500 dark:border-neutral-700">
              Select a document to see the extracted data, the checks and the correction form.
            </section>
          )}
        </div>
      </div>
    </main>
  );
}