"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/useAuth";

type GitHubStatus = { app_registered: boolean; app_id: string | null; manifest_url: string };
type Installation = { installation_id: number; account_login: string; account_type: string };
type Repo = {
  full_name: string; private: boolean; default_branch: string;
  html_url: string; description: string | null; monitored: boolean;
  monitored_id: string | null; deploy_url: string | null;
};

export default function OnboardingGitHubPage() {
  const { user, loading, authedFetch } = useAuth();
  const router = useRouter();
  const params = useSearchParams();

  const [appStatus, setAppStatus] = useState<GitHubStatus | null>(null);
  const [installations, setInstallations] = useState<Installation[]>([]);
  const [selectedInstall, setSelectedInstall] = useState<number | null>(null);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [deployUrls, setDeployUrls] = useState<Record<string, string>>({});
  const [provisioning, setProvisioning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Auth gate
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  // Load App + installation state
  const refresh = useCallback(async () => {
    if (!user) return;
    setError(null);
    try {
      const sRes = await fetch(`${process.env.NEXT_PUBLIC_API}/api/github/status`);
      setAppStatus(await sRes.json());

      const iRes = await authedFetch("/api/github/installations");
      const insts: Installation[] = await iRes.json();
      setInstallations(insts);
      if (insts.length > 0 && selectedInstall === null) {
        setSelectedInstall(insts[0].installation_id);
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    }
  }, [user, authedFetch, selectedInstall]);

  useEffect(() => { refresh(); }, [refresh]);

  // Adopt installation_id from query string if just returned from GitHub
  useEffect(() => {
    const fromQS = params.get("installation_id");
    if (fromQS) setSelectedInstall(Number(fromQS));
  }, [params]);

  // Load repos when installation changes
  useEffect(() => {
    if (!user || !selectedInstall) return;
    (async () => {
      try {
        const r = await authedFetch(`/api/github/installations/${selectedInstall}/repos`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const list: Repo[] = await r.json();
        setRepos(list);
      } catch (e: any) {
        setError(e?.message || "Failed to list repos");
      }
    })();
  }, [selectedInstall, user, authedFetch]);

  async function provision(repo: Repo) {
    if (!selectedInstall) return;
    const url = deployUrls[repo.full_name] || repo.deploy_url || "";
    if (!url) {
      setError(`Enter a deploy URL for ${repo.full_name} first`);
      return;
    }
    setProvisioning(repo.full_name);
    setError(null);
    try {
      const r = await authedFetch("/api/github/provision", {
        method: "POST",
        body: JSON.stringify({
          installation_id: selectedInstall,
          full_name: repo.full_name,
          deploy_url: url,
          deploy_provider: detectProvider(url),
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      await refresh();
      // Refresh the repo list too
      const list = await (await authedFetch(`/api/github/installations/${selectedInstall}/repos`)).json();
      setRepos(list);
    } catch (e: any) {
      setError(e?.message || "Provision failed");
    } finally {
      setProvisioning(null);
    }
  }

  if (loading) return <div className="dashboard-shell"><p>Loading…</p></div>;
  if (!user) return null;

  return (
    <main className="dashboard-shell">
      <header style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h1 style={{ margin: "0 0 4px 0" }}>🔌 Connect GitHub</h1>
          <p style={{ color: "#64748b", margin: 0 }}>
            Pick the repos Shotgun should monitor.
          </p>
        </div>
        <a href="/dashboard" style={{ color: "#475569", textDecoration: "none" }}>← back</a>
      </header>

      {error && (
        <div style={{ background: "#fef2f2", color: "#b91c1c", padding: 12, borderRadius: 8, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {/* Step 1 — App registration (one-time) */}
      {appStatus && !appStatus.app_registered && (
        <Card title="Step 1 · Register the GitHub App (admin one-time)">
          <p>
            The Shotgun App lives in your GitHub org and gives Shotgun the
            scoped permissions to commit the monitor workflow + open PRs.
          </p>
          <a className="primary-btn" href={appStatus.manifest_url}>
            Register on GitHub →
          </a>
        </Card>
      )}

      {/* Step 2 — Install on repos */}
      {appStatus?.app_registered && installations.length === 0 && (
        <Card title="Step 2 · Install on your repos">
          <p>
            Pick which repos Shotgun should have access to. You can change
            this any time from the GitHub App settings.
          </p>
          <a className="primary-btn" href={`${process.env.NEXT_PUBLIC_API}/api/github/install`}>
            Install Shotgun →
          </a>
        </Card>
      )}

      {/* Step 3 — Pick a repo + deploy URL */}
      {installations.length > 0 && (
        <Card title={`Step 3 · Pick a repo to monitor (${installations[0]?.account_login})`}>
          {installations.length > 1 && (
            <select
              value={selectedInstall ?? ""}
              onChange={(e) => setSelectedInstall(Number(e.target.value))}
              style={{ marginBottom: 12 }}
            >
              {installations.map((i) => (
                <option key={i.installation_id} value={i.installation_id}>
                  {i.account_login} ({i.account_type})
                </option>
              ))}
            </select>
          )}

          <div style={{ display: "grid", gap: 10 }}>
            {repos.length === 0 && <p style={{ color: "#64748b" }}>No repos accessible to this installation.</p>}
            {repos.map((r) => (
              <div key={r.full_name} className="repo-row">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <strong>{r.full_name}</strong>{" "}
                    {r.private && <span style={{ fontSize: 10, color: "#64748b" }}>PRIVATE</span>}
                    <div style={{ color: "#64748b", fontSize: 13 }}>{r.description}</div>
                  </div>
                  {r.monitored ? (
                    <span style={{ background: "#dcfce7", color: "#15803d", padding: "4px 8px", borderRadius: 6, fontSize: 12 }}>
                      ✓ monitored
                    </span>
                  ) : (
                    <span style={{ color: "#94a3b8", fontSize: 12 }}>not monitored</span>
                  )}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <input
                    type="url"
                    placeholder="https://your-live-deploy.example.com"
                    value={deployUrls[r.full_name] ?? r.deploy_url ?? ""}
                    onChange={(e) =>
                      setDeployUrls((d) => ({ ...d, [r.full_name]: e.target.value }))
                    }
                    style={{
                      flex: 1, padding: "8px 10px",
                      border: "1px solid #cbd5e1", borderRadius: 6,
                    }}
                  />
                  <button
                    onClick={() => provision(r)}
                    disabled={provisioning === r.full_name}
                    className="primary-btn"
                  >
                    {provisioning === r.full_name ? "…" : r.monitored ? "Re-sync" : "Monitor"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </main>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{
      background: "white", padding: 24, borderRadius: 12,
      border: "1px solid #e2e8f0", marginBottom: 16,
    }}>
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

function detectProvider(url: string): string {
  const u = url.toLowerCase();
  if (u.includes(".onrender.com")) return "render";
  if (u.includes(".vercel.app")) return "vercel";
  if (u.includes(".netlify.app")) return "netlify";
  if (u.includes("github.io")) return "gh_pages";
  return "other";
}
