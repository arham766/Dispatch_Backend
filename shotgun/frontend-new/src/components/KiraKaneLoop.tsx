"use client";

import { useEffect, useState } from "react";

const PHASES = [
  { dir: "rtk" as const, from: "kira", to: "kane", action: "send check_payload" },
  { dir: "ktr" as const, from: "kane", to: "kira", action: "verify · passed" },
];

const DOT_COUNT = 4;
const PHASE_MS = 3500;

export function KiraKaneLoop() {
  const [phaseIdx, setPhaseIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setPhaseIdx((p) => (p + 1) % PHASES.length),
      PHASE_MS,
    );
    return () => clearInterval(id);
  }, []);

  const phase = PHASES[phaseIdx];

  return (
    <div className="flex items-center gap-3 text-white">
      <Avatar src="/kira.jpg" label="Kira" />
      <div className="relative w-28 md:w-36 h-9 flex items-center">
        <span aria-hidden className="block w-full h-px bg-white/15" />
        <div className="absolute inset-0 flex items-center pointer-events-none">
          {Array.from({ length: DOT_COUNT }).map((_, i) => (
            <span
              key={`${phase.dir}-${i}`}
              aria-hidden
              className="absolute h-1.5 w-1.5 rounded-full"
              style={{
                top: "50%",
                marginTop: "-3px",
                backgroundColor: "#e85d1a",
                boxShadow: "0 0 8px #e85d1a",
                animation: `kk-${phase.dir} 1.6s linear ${
                  (i * 1.6) / DOT_COUNT
                }s infinite`,
              }}
            />
          ))}
        </div>
      </div>
      <Avatar src="/kane.png" label="Kane" />
      <div className="hidden md:flex flex-col ml-2 text-[11px] leading-tight w-[180px]">
        <span className="text-white/40 truncate">
          {phase.from} → {phase.to}
        </span>
        <span className="text-white truncate">{phase.action}</span>
      </div>
      <style>{`
        @keyframes kk-rtk {
          0%   { left: -4%;  opacity: 0; }
          12%  { opacity: 1; }
          88%  { opacity: 1; }
          100% { left: 104%; opacity: 0; }
        }
        @keyframes kk-ktr {
          0%   { left: 104%; opacity: 0; }
          12%  { opacity: 1; }
          88%  { opacity: 1; }
          100% { left: -4%;  opacity: 0; }
        }
      `}</style>
    </div>
  );
}

function Avatar({ src, label }: { src: string; label: string }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative h-9 w-9 rounded-full overflow-hidden border border-white/15">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={label}
          className="w-full h-full object-cover"
          draggable={false}
        />
      </div>
      <span className="text-[10px] uppercase tracking-[0.18em] text-white/60">
        {label}
      </span>
    </div>
  );
}
