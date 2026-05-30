"use client";

import { PatchDiff } from "@pierre/diffs/react";

// Unified diffs require every hunk body line to have a prefix
// (' ', '+', '-', '\'). Some sources emit bare blank lines for
// blank context lines, which @pierre/diffs rejects with
// "parseLineType: Invalid firstChar". Convert any blank line that
// appears after the first @@ hunk header into a space-prefixed
// blank context line.
function normalizeFilePatch(patch: string): string {
  const lines = patch.split("\n");
  let inHunk = false;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith("@@")) {
      inHunk = true;
      continue;
    }
    if (inHunk && lines[i].length === 0) {
      lines[i] = " ";
    }
  }
  return lines.join("\n").replace(/\s+$/g, "");
}

function splitPatchByFile(patch: string): string[] {
  const parts: string[] = [];
  const re = /^diff --git .+$/gm;
  const indices: number[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(patch)) !== null) indices.push(m.index);
  if (indices.length === 0) {
    const normalized = normalizeFilePatch(patch);
    return normalized ? [normalized] : [];
  }
  for (let i = 0; i < indices.length; i++) {
    const start = indices[i];
    const end = i + 1 < indices.length ? indices[i + 1] : patch.length;
    parts.push(normalizeFilePatch(patch.slice(start, end)));
  }
  return parts;
}

function extractFilename(filePatch: string): string {
  const m = filePatch.match(/^diff --git a\/(\S+) b\/(\S+)/m);
  if (m) return m[2];
  return "changed file";
}

export function DiffViewer({ patch }: { patch: string }) {
  const files = splitPatchByFile(patch);
  const lines = patch.split("\n");
  const additions = lines.filter(
    (l) => l.startsWith("+") && !l.startsWith("+++"),
  ).length;
  const deletions = lines.filter(
    (l) => l.startsWith("-") && !l.startsWith("---"),
  ).length;

  return (
    <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
      <div className="px-6 py-4 border-b border-[var(--color-border)] flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] font-mono">
            Diff
          </h2>
          <p className="mt-1 text-sm text-[var(--color-text)]">
            {files.length} {files.length === 1 ? "file" : "files"} changed
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm font-mono">
          <span className="text-[var(--color-success)]">+{additions}</span>
          <span className="text-[var(--color-danger)]">−{deletions}</span>
        </div>
      </div>
      <div className="divide-y divide-[var(--color-border)] bg-[var(--color-bg)]">
        {files.map((filePatch, i) => (
          <div key={i}>
            <div className="px-6 py-2 bg-[var(--color-surface-muted)] text-xs font-mono text-[var(--color-text-muted)]">
              {extractFilename(filePatch)}
            </div>
            <div className="text-sm">
              <PatchDiff patch={filePatch} disableWorkerPool />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
