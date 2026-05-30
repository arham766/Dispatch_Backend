import Link from "next/link";
import { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-bg)] text-[var(--color-text)]">
      <header className="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-[var(--color-flame)]" />
            <span className="text-xl tracking-tight text-[var(--color-cream)]">
              Dispatch
            </span>
          </Link>
          <nav className="flex items-center gap-5 text-sm font-mono">
            <Link
              href="/incidents"
              className="text-[var(--color-text-muted)] hover:text-[var(--color-cream)] hover:underline underline-offset-4"
            >
              incidents
            </Link>
            <Link
              href="/"
              className="text-[var(--color-text-muted)] hover:text-[var(--color-cream)] hover:underline underline-offset-4"
            >
              home
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1">
        <div className="mx-auto max-w-6xl px-6 py-8">{children}</div>
      </main>
      <footer className="border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="mx-auto max-w-6xl px-6 py-4 text-xs text-[var(--color-text-muted)] font-mono">
          dispatch · v0.1
        </div>
      </footer>
    </div>
  );
}
