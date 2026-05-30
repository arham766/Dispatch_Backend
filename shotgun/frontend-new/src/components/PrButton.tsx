export function PrButton({ prUrl }: { prUrl: string | null }) {
  const disabled = !prUrl;
  if (disabled) {
    return (
      <button
        disabled
        className="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-mono bg-[var(--color-surface)] text-[var(--color-text-muted)] border border-[var(--color-border)] cursor-not-allowed"
      >
        PR not yet opened
      </button>
    );
  }
  return (
    <a
      href={prUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-mono bg-[var(--color-flame)] text-[#0d0a08] hover:bg-[var(--color-cream)] transition-colors"
    >
      Open pull request ↗
    </a>
  );
}
