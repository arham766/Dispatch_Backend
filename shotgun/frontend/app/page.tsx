"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/useAuth";

/**
 * Root page: dispatcher.
 *
 * Sends signed-in users to /dashboard and signed-out users to /login.
 * The live monitor lives at /incident (with ?run=<id>) so it can be
 * deep-linked from emails / dashboards / GitHub PR comments.
 */
export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/dashboard" : "/login");
  }, [user, loading, router]);

  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <p style={{ color: "#64748b" }}>Loading…</p>
    </main>
  );
}
