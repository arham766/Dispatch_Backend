export function DiagnosisCard({
  symptom,
  diagnosis,
}: {
  symptom: string;
  diagnosis: string | null;
}) {
  return (
    <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] font-mono">
        Symptom
      </h2>
      <p className="mt-2 text-[var(--color-text)] text-lg leading-snug">
        {symptom}
      </p>
      <div className="mt-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] font-mono">
          Diagnosis
        </h2>
        {diagnosis ? (
          <p className="mt-2 text-[var(--color-text-soft)] leading-relaxed">
            {diagnosis}
          </p>
        ) : (
          <p className="mt-2 text-[var(--color-text-muted)] italic">
            Diagnosis pending…
          </p>
        )}
      </div>
    </section>
  );
}
