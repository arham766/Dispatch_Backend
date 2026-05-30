"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  GithubFreeIcons,
  RepositoryFreeIcons,
  GitBranchFreeIcons,
} from "@hugeicons/core-free-icons";
import { ShaderBackground } from "@/components/ShaderBackground";
import { useAuth } from "@/lib/useAuth";
import { makeApi, type Me } from "@/lib/api";

interface RepoOption {
  id: string;
  org: string;
  name: string;
  full_name: string;
  description: string;
  language: string;
  default_branch: string;
  private: boolean;
  monitored: boolean;
  monitored_repo_id: string | null;
  installation_id: number | null;
  current_deploy_url: string | null;
}

function detectProvider(url: string): string {
  const u = url.toLowerCase();
  if (u.includes(".onrender.com")) return "render";
  if (u.includes(".vercel.app")) return "vercel";
  if (u.includes(".netlify.app")) return "netlify";
  if (u.includes("github.io")) return "gh_pages";
  return "other";
}

export default function ProjectsPage() {
  const { user, loading, authedFetch, signOut } = useAuth();
  const router = useRouter();
  const api = useMemo(() => makeApi(authedFetch), [authedFetch]);

  const [me, setMe] = useState<Me | null>(null);
  const [repos, setRepos] = useState<RepoOption[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [draftUrl, setDraftUrl] = useState<string>("");
  const [provisioning, setProvisioning] = useState<string | null>(null);
  const [installUrl, setInstallUrl] = useState<string>("#");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  useEffect(() => {
    api.githubInstallUrl().then(setInstallUrl).catch(() => {});
  }, [api]);

  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        const data = await api.me();
        setMe(data);
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : "Failed to load profile");
      }
    })();
  }, [user, api]);

  useEffect(() => {
    if (!me) return;
    (async () => {
      const acc = me.installations[0]?.account_login || "you";

      const monitored: RepoOption[] = me.monitored_repos.map((r) => {
        const [org, name] = r.full_name.split("/");
        return {
          id: r.id,
          org: org || acc,
          name: name || r.full_name,
          full_name: r.full_name,
          description: `${r.deploy_url}${r.is_local_loop ? " · local loop" : ""}`,
          language: r.deploy_provider,
          default_branch: "main",
          private: false,
          monitored: true,
          monitored_repo_id: r.id,
          installation_id: null,
          current_deploy_url: r.deploy_url,
        };
      });

      let extras: RepoOption[] = [];
      if (me.installations.length > 0) {
        try {
          const installId = me.installations[0].installation_id;
          const list = await api.listInstallationRepos(installId);
          extras = list
            .filter((r) => !r.monitored)
            .map((r) => {
              const [org, name] = r.full_name.split("/");
              return {
                id: `inst-${installId}-${r.full_name}`,
                org: org || acc,
                name: name || r.full_name,
                full_name: r.full_name,
                description: r.description || "Pick to start watching",
                language: "—",
                default_branch: r.default_branch,
                private: r.private,
                monitored: false,
                monitored_repo_id: null,
                installation_id: installId,
                current_deploy_url: null,
              };
            });
        } catch {
          /* non-fatal */
        }
      }

      setRepos([...monitored, ...extras]);
    })();
  }, [me, api]);

  function toggleExpand(repo: RepoOption) {
    if (repo.monitored && repo.monitored_repo_id) {
      // Already monitored — go straight to its incident page.
      router.push(`/incidents`);
      return;
    }
    // Otherwise toggle the inline "live URL" prompt.
    if (expanded === repo.id) {
      setExpanded(null);
      setDraftUrl("");
    } else {
      setExpanded(repo.id);
      setDraftUrl(repo.current_deploy_url || "");
      setErr(null);
    }
  }

  async function startWatching(repo: RepoOption) {
    if (!repo.installation_id) return;
    const url = draftUrl.trim();
    if (!url || !/^https?:\/\//.test(url)) {
      setErr("Enter a full http(s) URL where your app is deployed.");
      return;
    }
    setProvisioning(repo.id);
    setErr(null);
    try {
      await api.provisionRepo({
        installation_id: repo.installation_id,
        full_name: repo.full_name,
        deploy_url: url,
        deploy_provider: detectProvider(url),
      });
      // Refresh + take the user to the dashboard.
      const fresh = await api.me();
      setMe(fresh);
      router.push("/incidents");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Provision failed");
    } finally {
      setProvisioning(null);
    }
  }

  if (loading || !user) return null;
  const accountLogin = me?.installations[0]?.account_login || me?.email || "you";

  return (
    <div className="relative min-h-screen w-full bg-black">
      <ShaderBackground />
      <div className="relative z-10 min-h-screen flex items-center justify-center px-4 md:px-6 py-12">
        <div className="w-full max-w-2xl rounded bg-black p-6 md:p-8">
          <div className="flex items-center justify-between gap-3 text-white/60 text-xs">
            <div className="flex items-center gap-3">
              <HugeiconsIcon
                icon={GithubFreeIcons}
                size={14}
                color="currentColor"
                strokeWidth={1.75}
              />
              <span>Signed in as @{accountLogin}</span>
            </div>
            <button
              type="button"
              onClick={signOut}
              className="text-white/40 hover:text-white"
            >
              Sign out
            </button>
          </div>

          <h1
            className="mt-4 text-white tracking-tight leading-[0.95]"
            style={{
              fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)",
              fontWeight: 300,
              letterSpacing: "-0.02em",
            }}
          >
            Add a project.
          </h1>
          <p className="mt-3 text-white/70 text-sm md:text-base leading-snug">
            Pick a repository to start watching. You can add more later.
          </p>

          {err ? (
            <p className="mt-4 text-xs text-red-300/80">{err}</p>
          ) : null}

          <ul className="mt-8 space-y-2">
            {repos.length === 0 && me ? (
              <li className="text-white/40 text-sm">
                No repositories yet.{" "}
                <Link
                  href={installUrl}
                  className="text-white underline underline-offset-4"
                >
                  Connect GitHub
                </Link>{" "}
                to grant Dispatch access to your repos.
              </li>
            ) : null}

            {repos.map((r) => {
              const isOpen = expanded === r.id;
              return (
                <li key={r.id}>
                  <div
                    className="group rounded-md bg-white/[0.04] hover:bg-white/[0.08] transition-colors"
                    style={{
                      boxShadow: isOpen
                        ? "inset 0 0 0 1px rgba(232,93,26,0.6)"
                        : "none",
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => toggleExpand(r)}
                      className="w-full flex items-center gap-3 p-3 text-left"
                    >
                      <span className="flex items-center justify-center h-9 w-9 rounded bg-black text-white/80 group-hover:text-white">
                        <HugeiconsIcon
                          icon={RepositoryFreeIcons}
                          size={16}
                          color="currentColor"
                          strokeWidth={1.75}
                        />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-white text-sm md:text-base truncate">
                          <span className="text-white/50">{r.org}/</span>
                          {r.name}
                          {r.private ? (
                            <span className="ml-2 text-[10px] uppercase tracking-wider text-white/40">
                              private
                            </span>
                          ) : null}
                          {r.monitored ? (
                            <span className="ml-2 text-[10px] uppercase tracking-wider text-emerald-300/80">
                              watching
                            </span>
                          ) : null}
                        </span>
                        <span className="block text-xs text-white/50 truncate mt-0.5">
                          {r.description}
                        </span>
                      </span>
                      <span className="hidden md:flex items-center gap-1.5 text-xs text-white/50">
                        <HugeiconsIcon
                          icon={GitBranchFreeIcons}
                          size={12}
                          color="currentColor"
                          strokeWidth={1.75}
                        />
                        {r.default_branch}
                      </span>
                      <span className="text-white/30 group-hover:text-white/70">
                        {r.monitored ? "↗" : isOpen ? "↓" : "+"}
                      </span>
                    </button>

                    {/* Inline "live URL" prompt for unmonitored repos */}
                    {isOpen && !r.monitored && r.installation_id ? (
                      <div className="px-3 pb-3 pt-1">
                        <label className="block text-[11px] uppercase tracking-wider text-white/40 mb-2">
                          Where is this repo deployed?
                        </label>
                        <div className="flex gap-2">
                          <input
                            type="url"
                            autoFocus
                            placeholder="https://your-app.onrender.com"
                            value={draftUrl}
                            onChange={(e) => setDraftUrl(e.target.value)}
                            className="flex-1 bg-black border border-white/10 rounded px-3 py-2 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/40"
                          />
                          <button
                            type="button"
                            onClick={() => startWatching(r)}
                            disabled={provisioning === r.id}
                            className="text-sm text-black bg-white hover:bg-white/90 disabled:opacity-60 rounded px-3 py-2"
                          >
                            {provisioning === r.id ? "Saving…" : "Start watching"}
                          </button>
                        </div>
                        <p className="mt-2 text-[11px] text-white/40 leading-snug">
                          Dispatch will hit this URL with Kane whenever your app
                          deploys, and open a PR when the loop converges.
                        </p>
                      </div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>

          {/* Always-on "connect more repos" tail */}
          {me && me.installations.length === 0 ? (
            <div className="mt-8 pt-6 border-t border-white/10">
              <Link
                href={installUrl}
                className="inline-flex w-full items-center justify-center gap-2.5 text-sm text-white bg-white/10 hover:bg-white/20 rounded-md px-4 py-3 transition-colors"
              >
                <HugeiconsIcon
                  icon={GithubFreeIcons}
                  size={16}
                  color="currentColor"
                  strokeWidth={1.75}
                />
                Connect GitHub
              </Link>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
