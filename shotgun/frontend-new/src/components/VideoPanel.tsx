"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { PlayFreeIcons } from "@hugeicons/core-free-icons";
import { Media } from "@/lib/types";

type Tab = "before" | "after";

export function VideoPanel({
  before,
  after,
}: {
  before: Media | null;
  after: Media | null;
}) {
  const [tab, setTab] = useState<Tab>("after");
  const active = tab === "before" ? before : after;

  return (
    <div className="rounded-lg overflow-hidden bg-black border border-white/10">
      <div className="flex items-center border-b border-white/10">
        <TabButton active={tab === "before"} onClick={() => setTab("before")}>
          Before fix
        </TabButton>
        <TabButton active={tab === "after"} onClick={() => setTab("after")}>
          After fix
        </TabButton>
      </div>
      <div className="relative aspect-video bg-black">
        {active ? (
          <>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-6">
              <span
                className="text-[10px] uppercase tracking-[0.25em]"
                style={{ color: active.accent ?? "#ffffff", opacity: 0.7 }}
              >
                {tab === "before" ? "Failing flow" : "Passing flow"}
              </span>
              <span
                className="mt-2 text-lg md:text-xl text-white leading-snug"
                style={{ fontWeight: 400 }}
              >
                {active.caption ?? (tab === "before" ? "Before fix" : "After fix")}
              </span>
            </div>
            {active.replay_url ? (
              <a
                href={active.replay_url}
                target="_blank"
                rel="noopener noreferrer"
                className="absolute inset-0 flex items-center justify-center group"
                aria-label="Watch full replay"
              >
                <span className="flex items-center justify-center h-14 w-14 rounded-full bg-black/60 backdrop-blur-sm border border-white/30 text-white group-hover:scale-105 group-hover:border-white/60 transition-all">
                  <HugeiconsIcon
                    icon={PlayFreeIcons}
                    size={22}
                    color="currentColor"
                    strokeWidth={2}
                  />
                </span>
              </a>
            ) : null}
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-white/40 text-sm">
            {tab === "before" ? "Capturing failing flow…" : "Waiting for verify…"}
          </div>
        )}
      </div>
      {active?.replay_url ? (
        <div className="px-3 py-2 flex items-center justify-between text-xs bg-black">
          <span className="text-white">
            {tab === "before" ? "Failing flow" : "Passing flow"}
          </span>
          <a
            href={active.replay_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-white/60 hover:text-white"
          >
            Open in Kane ↗
          </a>
        </div>
      ) : null}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative flex-1 px-4 py-2.5 text-sm bg-black transition-colors ${
        active ? "text-white" : "text-white/40 hover:text-white/70"
      }`}
    >
      {children}
      {active ? (
        <span className="absolute left-0 right-0 bottom-0 h-px bg-white" />
      ) : null}
    </button>
  );
}
