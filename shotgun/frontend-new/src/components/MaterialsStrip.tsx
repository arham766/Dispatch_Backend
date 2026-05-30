import { SupportingMaterial } from "@/lib/mock";

export function MaterialsStrip({ items }: { items: SupportingMaterial[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="text-sm text-white mb-3">Supporting material</h3>
      <div className="grid grid-cols-2 gap-2">
        {items.map((m) => (
          <a
            key={m.id}
            href={m.src}
            target="_blank"
            rel="noopener noreferrer"
            className="group block rounded-lg overflow-hidden border border-white/10 bg-black hover:border-white/30 transition-colors"
          >
            <div className="relative aspect-video bg-black overflow-hidden flex flex-col items-center justify-center px-4 text-center">
              <span
                className="text-[10px] uppercase tracking-[0.25em]"
                style={{ color: m.accent ?? "#ffffff", opacity: 0.75 }}
              >
                {m.label}
              </span>
              {m.caption ? (
                <span className="mt-2 text-sm text-white leading-snug truncate max-w-full">
                  {m.caption}
                </span>
              ) : null}
            </div>
            <div className="px-3 py-2 flex items-center justify-between gap-2 bg-black text-xs">
              <span className="text-white truncate">{m.label}</span>
              <span className="text-white/60 group-hover:text-white transition-colors">
                {m.kind} ↗
              </span>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
