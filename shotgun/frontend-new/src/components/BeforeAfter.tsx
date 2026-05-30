import { Media, Status } from "@/lib/types";
import { MediaPanel } from "./MediaPanel";

export function BeforeAfter({
  before,
  after,
  status,
}: {
  before: Media | null;
  after: Media | null;
  status: Status;
}) {
  const showAfter = status === "RESOLVED" || status === "PR_OPENING";
  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] font-mono mb-3">
        Proof
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <MediaPanel kind="before" media={before} />
        <div
          className={`transition-opacity duration-500 ${
            showAfter ? "opacity-100" : "opacity-60"
          }`}
        >
          <MediaPanel kind="after" media={showAfter ? after : null} />
        </div>
      </div>
    </section>
  );
}
