"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/useAuth";

type Me = {
  uid: string; email: string; name: string | null; picture: string | null;
  is_admin: boolean;
  installations: { installation_id: number; account_login: string; account_type: string }[];
  monitored_repos: {
    id: string; full_name: string; deploy_url: string;
    deploy_provider: string; monitoring_enabled: boolean;
    is_local_loop: boolean;
  }[];
};

export default function DashboardPage() {
  const { user, loading, signOut, authedFetch } = useAuth();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  const refresh = useCallback(async () => {
    if (!user) return;
    try {
      const r = await authedFetch("/api/me");
      if (!r.ok) throw new Error(`/api/me ${r.status}`);
      setMe(await r.json());
    } catch (e: any) {
      setError(e?.message || "Failed to load profile");
    }
  }, [user, authedFetch]);

  useEffect(() => { refresh(); }, [refresh]);

  async function triggerRepo(repo: Me["monitored_repos"][number]) {
    setTriggering(repo.id);
    setError(null);
    try {
      if (repo.is_local_loop) {
        // Admin / demo mode: fire the local orchestrator directly.
        // `recent_diff_hint` is what the fallback patcher uses to pick
        // a fix recipe — pass "payment.js" for the seeded checkout demo
        // so cardNumbr → cardNumber lands when Kiro Desktop doesn't drive.
        const r = await authedFetch("/incidents", {
          method: "POST",
          body: JSON.stringify({
            service: "checkout",
            symptom: `Checkout 500 on pay — ${repo.full_name}`,
            suspect_url: repo.deploy_url,
            repro_flow: "flows/checkout_test.md",
            recent_diff_hint: "payment.js",
            source: "manual",
          }),
        });
        if (!r.ok) throw new Error(await r.text());
        const { run_id } = await r.json();
        router.push(`/incident?run=${run_id}`);
      } else {
        // Production path: fire repository_dispatch via the GitHub App.
        const r = await authedFetch(`/api/github/repos/${repo.id}/trigger`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        if (!r.ok) throw new Error(await r.text());
        const { incident_id } = await r.json();
        router.push(`/incident?run=${incident_id}`);
      }
    } catch (e: any) {
      setError(e?.message || "Trigger failed");
    } finally {
      setTriggering(null);
    }
  }

  if (loading || !me) return <div className="dashboard-shell"><p>Loading…</p></div>;
  if (!user) return null;

  return (
    <main className="dashboard-shell">
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1>🎯 Shotgun</h1>
          <p style={{ color: "#64748b", margin: 0 }}>
            Signed in as <strong>{me.email}</strong>
            {me.is_admin && (
              <span style={{ marginLeft: 8, background: "#fef3c7", color: "#92400e", padding: "2px 8px", borderRadius: 6, fontSize: 11 }}>
                ADMIN
              </span>
            )}
          </p>
        </div>
        <button className="signout" onClick={signOut}>Sign out</button>
      </header>

      {error && (
        <div style={{ background: "#fef2f2", color: "#b91c1c", padding: 12, borderRadius: 8, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {/* Monitored repos */}
      <section style={{
        background: "white", padding: 24, borderRadius: 12,
        border: "1px solid #e2e8f0", marginBottom: 16,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Monitored repos</h2>
          <a
            href="/onboarding/github"
            style={{
              background: "#0f172a", color: "white", padding: "8px 14px",
              borderRadius: 8, textDecoration: "none", fontSize: 14,
            }}
          >
            + Add repo
          </a>
        </div>

        {me.monitored_repos.length === 0 && (
          <p style={{ color: "#64748b" }}>
            No repos yet. Click <strong>+ Add repo</strong> to install the Shotgun GitHub App and pick one.
          </p>
        )}

        <div style={{ display: "grid", gap: 12 }}>
          {me.monitored_repos.map((r) => (
            <div key={r.id} className="repo-row">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <strong>{r.full_name}</strong>
                  {r.is_local_loop && (
                    <span style={{ marginLeft: 8, background: "#dbeafe", color: "#1e40af", padding: "2px 8px", borderRadius: 6, fontSize: 11 }}>
                      LOCAL LOOP
                    </span>
                  )}
                  <div style={{ color: "#64748b", fontSize: 13, marginTop: 2 }}>
                    Live URL: <code>{r.deploy_url}</code>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => triggerRepo(r)}
                    disabled={triggering === r.id}
                    className="primary-btn"
                  >
                    {triggering === r.id ? "Firing…" : "🔔 Trigger run"}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Admin reminder */}
      {me.is_admin && (
        <section style={{
          background: "#fffbeb", border: "1px solid #fde68a",
          padding: 18, borderRadius: 12, color: "#92400e",
        }}>
          <strong>Admin demo mode active.</strong> Your monitored repo runs the local Kiro Desktop loop
          against <code>{me.monitored_repos[0]?.deploy_url}</code> using the existing PAT in
          <code> .env</code>. Other users go through the full GitHub App install flow.
        </section>
      )}
    </main>
  );
}
