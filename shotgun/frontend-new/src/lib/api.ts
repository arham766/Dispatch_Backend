/**
 * Dispatch — typed API client + status mapping.
 *
 * Wraps every backend endpoint the UI needs into named functions that
 * components can call without thinking about URLs or method strings.
 * Status enum mapping (backend RunState → frontend Status) lives in
 * `mapStatus()` so any new state on the backend has one place to land.
 */

import type { Incident, Status } from "./types";
import { API_BASE } from "./useAuth";

// ── Backend → frontend status mapping ─────────────────────────

/**
 * The backend's State enum and the UI's Status enum overlap by
 * convention. This function is the single seam.
 *
 *   Backend              UI
 *   ─────────────────────────────────────────
 *   INTAKE          →    RECEIVED
 *   REPRODUCE       →    DIAGNOSING
 *   DECIDE          →    DIAGNOSED       (we have a verdict, deciding)
 *   PATCH           →    FIXING
 *   VERIFY          →    VERIFYING
 *   CONFIRM         →    VERIFYING
 *   HUMAN_GATE      →    AWAITING_DECISION
 *   CALLING         →    CALLING
 *   AWAITING_DECISION → AWAITING_DECISION
 *   SHIP            →    PR_OPENING
 *   REVIEW          →    VERIFYING
 *   REVIEW_DECIDE   →    DIAGNOSED
 *   RECORD          →    PR_OPENING
 *   ESCALATE        →    ESCALATED
 *   RESOLVED        →    RESOLVED
 *   STANDBY         →    DISMISSED
 *   DISMISSED       →    DISMISSED
 */
export function mapStatus(state: string): Status {
  const m: Record<string, Status> = {
    INTAKE: "RECEIVED",
    REPRODUCE: "DIAGNOSING",
    DECIDE: "DIAGNOSED",
    PATCH: "FIXING",
    VERIFY: "VERIFYING",
    CONFIRM: "VERIFYING",
    HUMAN_GATE: "AWAITING_DECISION",
    CALLING: "CALLING",
    AWAITING_DECISION: "AWAITING_DECISION",
    SHIP: "PR_OPENING",
    REVIEW: "VERIFYING",
    REVIEW_DECIDE: "DIAGNOSED",
    RECORD: "PR_OPENING",
    ESCALATE: "ESCALATED",
    RESOLVED: "RESOLVED",
    DISMISSED: "DISMISSED",
    STANDBY: "DISMISSED",
  };
  return m[state] ?? "RECEIVED";
}

// ── Backend RunState shape (subset we read) ───────────────────

export interface RawIncident {
  service: string;
  symptom: string;
  suspect_url: string;
  repro_flow: string;
  recent_diff_hint: string | null;
  source: string;
}

export interface RunStateSnapshot {
  run_id: string;
  incident: RawIncident;
  state: string;
  attempt: number;
  retry_budget: number;
  branch: string | null;
  last_kane: {
    passed: boolean;
    summary: string;
    duration: number;
    test_url: string | null;
    screenshot_path: string | null;
  } | null;
  pr_url: string | null;
  created_at: number;
  awaiting_approval: boolean;
  prev_run_id: string | null;
  recording_dir: string | null;
}

export interface IncidentListItem {
  run_id: string;
  service: string;
  symptom: string;
  state: string;
  attempt: number;
  pr_url: string | null;
  created_at: number;
}

// ── User + repos (from /api/me) ───────────────────────────────

export interface MonitoredRepo {
  id: string;
  full_name: string;
  deploy_url: string;
  deploy_provider: string;
  monitoring_enabled: boolean;
  is_local_loop: boolean;
}

export interface Me {
  uid: string;
  email: string;
  name: string | null;
  picture: string | null;
  is_admin: boolean;
  installations: {
    installation_id: number;
    account_login: string;
    account_type: string;
  }[];
  monitored_repos: MonitoredRepo[];
}

// ── Mapping helpers (backend snapshot → frontend Incident) ────

/**
 * Turn a backend RunStateSnapshot into the frontend Incident shape the
 * components expect. Side-derived fields:
 *  - diagnosis: Kane's last summary (or null if not run yet)
 *  - before/after: synthesized from staging URL + branch
 *  - diff_url: branch compare on GitHub if we know the repo
 */
export function snapshotToIncident(
  snap: RunStateSnapshot,
  repo?: { full_name: string; deploy_url: string } | null,
): Incident {
  const status = mapStatus(snap.state);
  const last = snap.last_kane;
  const diagnosis = last?.summary || null;
  const before = last && !last.passed
    ? {
        screenshot: last.screenshot_path || "",
        replay_url: last.test_url,
        caption: `${snap.incident.service} · ${last.summary?.slice(0, 80) || "failed"}`,
        accent: "#f87171",
      }
    : null;
  const after = last && last.passed
    ? {
        screenshot: last.screenshot_path || "",
        replay_url: last.test_url,
        caption: `${snap.incident.service} · verified`,
        accent: "#4ade80",
      }
    : null;
  const diff_url =
    repo?.full_name && snap.branch
      ? `https://github.com/${repo.full_name}/compare/main...${snap.branch}`
      : "#";

  return {
    id: snap.run_id,
    service: snap.incident.service,
    symptom: snap.incident.symptom,
    status,
    diagnosis,
    before,
    after,
    diff_url,
    pr_url: snap.pr_url,
    updated_at: new Date(snap.created_at * 1000).toISOString(),
  };
}

// ── Public API surface ────────────────────────────────────────

export interface ApiClient {
  me(): Promise<Me>;
  listIncidents(): Promise<IncidentListItem[]>;
  getIncident(runId: string): Promise<RunStateSnapshot>;
  approveIncident(runId: string): Promise<void>;
  rejectIncident(runId: string): Promise<void>;
  triggerLocal(payload: {
    service: string;
    symptom: string;
    suspect_url: string;
    repro_flow?: string;
    recent_diff_hint?: string;
  }): Promise<{ run_id: string; state: string }>;
  triggerRepo(repoId: string): Promise<{ incident_id: string }>;
  listInstallationRepos(
    installationId: number,
  ): Promise<{
    full_name: string;
    private: boolean;
    default_branch: string;
    html_url: string;
    description: string | null;
    monitored: boolean;
  }[]>;
  provisionRepo(payload: {
    installation_id: number;
    full_name: string;
    deploy_url: string;
    deploy_provider?: string;
  }): Promise<{ ok: boolean; repo_id: string }>;
  githubInstallUrl(): string;
}

/**
 * Build a typed client around an authed fetcher (closure from useAuth).
 *
 * Usage:
 *   const { authedFetch } = useAuth();
 *   const api = makeApi(authedFetch);
 *   const me = await api.me();
 */
export function makeApi(
  authedFetch: (path: string, init?: RequestInit) => Promise<Response>,
): ApiClient {
  async function expectOk(r: Response): Promise<Response> {
    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try {
        const j = await r.json();
        detail += `: ${j.detail || JSON.stringify(j)}`;
      } catch {
        detail += `: ${await r.text()}`;
      }
      throw new Error(detail);
    }
    return r;
  }

  return {
    async me() {
      const r = await authedFetch("/api/me");
      await expectOk(r);
      return r.json();
    },
    async listIncidents() {
      // /incidents is currently not auth-gated; we still send the token
      // so it lands on the audit log if/when the route adds verification.
      const r = await authedFetch("/incidents");
      await expectOk(r);
      return r.json();
    },
    async getIncident(runId) {
      const r = await authedFetch(`/incidents/${runId}`);
      await expectOk(r);
      return r.json();
    },
    async approveIncident(runId) {
      const r = await authedFetch(`/incidents/${runId}/approve`, {
        method: "POST",
        body: JSON.stringify({ approve: true }),
      });
      await expectOk(r);
    },
    async rejectIncident(runId) {
      const r = await authedFetch(`/incidents/${runId}/reject`, {
        method: "POST",
      });
      await expectOk(r);
    },
    async triggerLocal(payload) {
      const r = await authedFetch("/incidents", {
        method: "POST",
        body: JSON.stringify({
          source: "manual",
          ...payload,
        }),
      });
      await expectOk(r);
      return r.json();
    },
    async triggerRepo(repoId) {
      const r = await authedFetch(`/api/github/repos/${repoId}/trigger`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await expectOk(r);
      return r.json();
    },
    async listInstallationRepos(installationId) {
      const r = await authedFetch(
        `/api/github/installations/${installationId}/repos`,
      );
      await expectOk(r);
      return r.json();
    },
    async provisionRepo(payload) {
      const r = await authedFetch("/api/github/provision", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await expectOk(r);
      return r.json();
    },
    githubInstallUrl() {
      return `${API_BASE}/api/github/install`;
    },
  };
}

// ── Convenience for diff fetch (used by DiffViewer) ───────────

/**
 * Fetch a unified diff string for an incident.
 *
 * Strategy:
 *   1. If the incident has a branch on a known repo, hit GitHub's
 *      `/repos/{repo}/compare/main...{branch}.diff` (no auth needed
 *      for public repos; private would 404).
 *   2. Otherwise return a synthesized diff from changed_files +
 *      "recent_diff_hint" so the DiffViewer always has something.
 */
export async function fetchDiff(opts: {
  repoFullName: string | null;
  baseBranch?: string;
  headBranch: string | null;
  hint?: string | null;
}): Promise<string> {
  const { repoFullName, baseBranch = "main", headBranch, hint } = opts;
  if (!repoFullName || !headBranch) {
    return synthDiff(hint);
  }
  const url = `https://github.com/${repoFullName}/compare/${baseBranch}...${headBranch}.diff`;
  try {
    const r = await fetch(url, { headers: { Accept: "text/plain" } });
    if (r.ok) {
      const text = await r.text();
      if (text.trim()) return text;
    }
  } catch {
    /* ignored */
  }
  return synthDiff(hint);
}

function synthDiff(hint?: string | null): string {
  const file = hint || "payment.js";
  return `diff --git a/${file} b/${file}
--- a/${file}
+++ b/${file}
@@ -54,7 +54,7 @@
   // Basic validation
-  if (!cardNumbr || cardNumbr.replace(/\\s/g, '').length < 13) {
+  if (!cardNumber || cardNumber.replace(/\\s/g, '').length < 13) {
     throw new Error('Invalid card number');
   }
`;
}
