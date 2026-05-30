import { Media } from "@/lib/types";

export function MediaPanel({
  kind,
  media,
}: {
  kind: "before" | "after";
  media: Media | null;
}) {
  const isBefore = kind === "before";
  const accent = isBefore ? "var(--color-danger)" : "var(--color-success)";
  const title = isBefore ? "Before" : "After";
  const subtitle = isBefore ? "Failing flow" : "Passing flow";

  if (!media) {
    return (
      <div className="rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-center">
        <div className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] font-mono">
          {title}
        </div>
        <p className="mt-3 text-sm text-[var(--color-text-muted)]">
          {isBefore ? "Capturing failing flow…" : "Waiting for fix to verify…"}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden flex flex-col">
      <div
        className="px-4 py-3 flex items-center justify-between border-b border-[var(--color-border)]"
        style={{
          backgroundColor: "color-mix(in srgb, " + accent + " 12%, transparent)",
        }}
      >
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: accent }}
          />
          <span
            className="text-sm font-mono uppercase tracking-wider"
            style={{ color: accent }}
          >
            {title}
          </span>
          <span className="text-xs text-[var(--color-text-muted)] font-mono">
            · {subtitle}
          </span>
        </div>
        {media.replay_url ? (
          <a
            href={media.replay_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-mono px-2.5 py-1 rounded-md border border-[var(--color-border)] text-[var(--color-text-soft)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-cream)] transition-colors"
          >
            Watch replay ↗
          </a>
        ) : null}
      </div>
      <div className="bg-[var(--color-bg)]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={media.screenshot}
          alt={`${title} screenshot`}
          className="w-full h-auto block"
        />
      </div>
    </div>
  );
}
