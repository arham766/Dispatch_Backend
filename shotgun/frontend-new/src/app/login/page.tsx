"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { HugeiconsIcon } from "@hugeicons/react";
import { GithubFreeIcons } from "@hugeicons/core-free-icons";
import { ShaderBackground } from "@/components/ShaderBackground";
import { useAuth } from "@/lib/useAuth";

export default function LoginPage() {
  const { user, loading, signInWithGithub, signInWithGoogle } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<null | "github" | "google">(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace("/projects");
  }, [user, loading, router]);

  async function handleGithub() {
    setBusy("github"); setErr(null);
    try {
      await signInWithGithub();
      router.replace("/projects");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Sign-in failed");
    } finally { setBusy(null); }
  }

  async function handleGoogle() {
    setBusy("google"); setErr(null);
    try {
      await signInWithGoogle();
      router.replace("/projects");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Sign-in failed");
    } finally { setBusy(null); }
  }

  return (
    <div className="relative min-h-screen w-full bg-black">
      <ShaderBackground />
      <div className="relative z-10 min-h-screen flex items-center justify-center px-4 md:px-6">
        <div className="w-full max-w-md rounded bg-black p-6 md:p-8">
          <h1
            className="text-white tracking-tight leading-[0.95]"
            style={{
              fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)",
              fontWeight: 300,
              letterSpacing: "-0.02em",
            }}
          >
            Sign in to Dispatch.
          </h1>
          <p className="mt-3 text-white/70 text-sm md:text-base leading-snug">
            Use your GitHub or Google account to connect repositories and start
            watching incidents.
          </p>

          <button
            type="button"
            onClick={handleGithub}
            disabled={busy !== null || loading}
            className="mt-8 inline-flex w-full items-center justify-center gap-2.5 text-sm md:text-base text-black bg-white hover:bg-white/90 disabled:opacity-60 rounded-md px-4 py-3 transition-colors"
          >
            <HugeiconsIcon
              icon={GithubFreeIcons}
              size={18}
              color="currentColor"
              strokeWidth={1.75}
            />
            {busy === "github" ? "Signing in…" : "Continue with GitHub"}
          </button>

          <button
            type="button"
            onClick={handleGoogle}
            disabled={busy !== null || loading}
            className="mt-3 inline-flex w-full items-center justify-center gap-2.5 text-sm md:text-base text-white bg-white/[0.06] hover:bg-white/[0.12] disabled:opacity-60 rounded-md px-4 py-3 transition-colors border border-white/10"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.43.34-2.09V7.07H2.18A11 11 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
            </svg>
            {busy === "google" ? "Signing in…" : "Continue with Google"}
          </button>

          {err ? (
            <p className="mt-3 text-xs text-red-300/80 leading-snug">{err}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
