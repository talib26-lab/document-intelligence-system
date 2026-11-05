"use client";

import { useRef, useState } from "react";
import { uploadDocuments, type UploadResult } from "@/lib/api";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.xlsx,.xls,.csv";
const MAX_FILES = 20;

export default function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(fileList: FileList | File[]) {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    setError(null);
    setResult(null);
    if (files.length > MAX_FILES) {
      setError(`Please upload at most ${MAX_FILES} files at once.`);
      return;
    }

    setUploading(true);
    try {
      const outcome = await uploadDocuments(files);
      setResult(outcome);
      if (outcome.accepted.length > 0) onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = ""; // allow picking the same file again
    }
  }

  return (
    <section aria-labelledby="upload-title" className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <h2 id="upload-title" className="text-lg font-semibold">
        Upload documents
      </h2>
      <p className="mt-1 text-sm text-neutral-500">
        PDF, JPG, PNG, TIFF, XLSX, XLS or CSV. Up to {MAX_FILES} files, 20 MB each.
      </p>

      <div
        role="button"
        tabIndex={0}
        aria-disabled={uploading}
        onClick={() => !uploading && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !uploading) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!uploading) void handleFiles(e.dataTransfer.files);
        }}
        className={`mt-4 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-10 text-center transition-colors ${
          dragging
            ? "border-blue-500 bg-blue-50 dark:bg-blue-950"
            : "border-neutral-300 hover:border-neutral-400 dark:border-neutral-700"
        } ${uploading ? "cursor-wait opacity-60" : ""}`}
      >
        <p className="font-medium">{uploading ? "Uploading..." : "Drop files here or click to choose"}</p>
        <p className="mt-1 text-xs text-neutral-500">Processing continues in the background after upload.</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => e.target.files && void handleFiles(e.target.files)}
        />
      </div>

      <div aria-live="polite" className="mt-4 space-y-2 text-sm">
        {error && (
          <p className="rounded-md bg-red-50 p-3 text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>
        )}

        {result && result.accepted.length > 0 && (
          <div className="rounded-md bg-green-50 p-3 text-green-800 dark:bg-green-950 dark:text-green-300">
            <p className="font-medium">
              {result.accepted.length} file{result.accepted.length > 1 ? "s" : ""} accepted
            </p>
            <ul className="mt-1 list-inside list-disc">
              {result.accepted.map((file) => (
                <li key={file.id}>{file.file_name}</li>
              ))}
            </ul>
          </div>
        )}

        {result && result.rejected.length > 0 && (
          <div className="rounded-md bg-red-50 p-3 text-red-800 dark:bg-red-950 dark:text-red-300">
            <p className="font-medium">
              {result.rejected.length} file{result.rejected.length > 1 ? "s" : ""} rejected
            </p>
            <ul className="mt-1 list-inside list-disc">
              {result.rejected.map((file, index) => (
                <li key={`${file.file_name}-${index}`}>
                  {file.file_name}: {file.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}