"""
Shotgun — Application configuration.

All settings are read from environment variables (or a .env file).
Grouped by concern: Kane, Kiro, GitHub, Orchestrator, Recording,
Review, Kafka, DB, Deploy, AgentPhone.
"""

from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


    # ── Kane CLI ──────────────────────────────────────
    LT_USERNAME: str = ""
    LT_ACCESS_KEY: str = ""
    KANE_HEADLESS: bool = True
    # When true, REPRODUCE / VERIFY / CONFIRM use a 2-sec curl smoke
    # check instead of full Kane CLI. Real Kane still runs once before
    # SHIP for the proof embedded in the PR. Use for fast iteration +
    # demos; set false for the audit-grade Kane on every step.
    KANE_FAST_MODE: bool = True
    # Whether to fire a single, slow, real Kane CLI run before SHIP
    # for the audit-grade artifact embedded in the PR. Set false for
    # demos (loop finishes in <2 min); true for production (PR gets
    # the LTM dashboard trace link).
    KANE_REAL_PROOF: bool = False

    # ── App under test ────────────────────────────────
    STAGING_BASE_URL: str = "https://dispatch-backend-i50g.onrender.com"

    # ── Kiro ──────────────────────────────────────────
    # Modes:
    #   cloud   — prod default. GitHub Contents API, no local git, no
    #             Kiro binary. Works on Render / any cloud host.
    #   desktop — local dev only. Invokes `kiro chat --mode agent`.
    #   hook    — legacy fallback. File-watch trigger.
    #   headless — stub kept for compat.
    KIRO_MODE: Literal["cloud", "desktop", "headless", "hook"] = "cloud"
    KIRO_WORKDIR: str = "/tmp"
    KIRO_TRIGGER_FILE: str = ".shotgun/trigger.json"

    # ── GitHub ────────────────────────────────────────
    GITHUB_TOKEN: str = ""
    GITHUB_REPO: str = ""
    GITHUB_BASE_BRANCH: str = "main"

    # ── Orchestrator ──────────────────────────────────
    RETRY_BUDGET: int = 3
    CONFIRMATION_RUNS: int = 3
    KANE_TIMEOUT_SECONDS: int = 120

    # ── Recording (§15) ──────────────────────────────
    RECORD_LOOPS: bool = True
    RECORDINGS_DIR: str = "./recordings"
    RECORD_RETENTION: int = 50
    RECORD_INDEX_FILE: str = "./recordings/index.json"

    # ── Kane Review (§16) ─────────────────────────────
    KANE_REVIEW_ENABLED: bool = False
    KANE_REVIEW_MODE: Literal["chained", "standalone"] = "chained"
    KANE_REVIEW_BUDGET: int = 2
    KANE_REVIEW_BLOCK_ON_REGRESSION: bool = True
    KANE_REVIEW_FLOWS_DIR: str = "./flows"
    KANE_REVIEW_CARRY_FORWARD: bool = True
    KANE_REVIEW_POST_AS: Literal["review", "comment"] = "review"

    # ── Kafka intake (§19) ────────────────────────────
    INTAKE_MODE: Literal["kafka", "postgres_queue", "webhook"] = "webhook"
    KAFKA_BROKERS: str = ""
    KAFKA_TOPIC: str = "frontend.incidents"
    KAFKA_GROUP_ID: str = "dispatch-orchestrator"
    KAFKA_USERNAME: str = ""
    KAFKA_PASSWORD: str = ""
    KAFKA_SASL_MECHANISM: str = "SCRAM-SHA-256"

    # ── Datastore — Postgres (§20) ────────────────────
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 5

    # ── Deploy / topology (§17–§18) ───────────────────
    PUBLIC_DASHBOARD_URL: str = ""
    LOOP_LOCATION: Literal["local"] = "local"
    STATUS_BUS: Literal["postgres", "tunnel"] = "postgres"
    STATUS_POLL_MS: int = 1000

    # ── AgentPhone — voice layer (§21) ────────────────
    AGENTPHONE_ENABLED: bool = False
    AGENTPHONE_API_URL: str = ""
    AGENTPHONE_API_KEY: str = ""
    AGENTPHONE_AGENT_ID: str = ""             # which agent places the call
    AGENTPHONE_FROM_NUMBER_ID: str = ""       # caller-ID number (optional, falls back to first)
    AGENTPHONE_FROM: str = ""                 # display only
    ONCALL_PHONE: str = ""                    # default destination
    AGENTPHONE_NO_ANSWER_TIMEOUT: int = 45

    # ── Resend (transactional email) ──────────────────
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "onboarding@resend.dev"
    RESEND_NOTIFY: str = ""
    RESEND_ENABLED: bool = False

    # ── Firebase Admin (server-side token verification) ──
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_SERVICE_ACCOUNT_JSON: str = ""    # one-line escaped JSON blob (preferred for cloud)
    FIREBASE_SERVICE_ACCOUNT_FILE: str = "/etc/secrets/trackyouridea-45c92-firebase-adminsdk-fbsvc-909243f66f.json"    # absolute path to the JSON file (preferred for local)

    # ── GitHub App (multi-tenant) ─────────────────────
    GITHUB_APP_ID: str = ""
    GITHUB_APP_PRIVATE_KEY: str = ""
    GITHUB_APP_CLIENT_ID: str = ""
    GITHUB_APP_CLIENT_SECRET: str = ""
    GITHUB_APP_WEBHOOK_SECRET: str = ""
    PUBLIC_APP_URL: str = "https://dispatch-backend-i50g.onrender.com"

    # ── Admin / demo mode ─────────────────────────────
    # Emails in ADMIN_EMAILS get a pre-monitored repo wired through the
    # existing PAT (GITHUB_TOKEN / GITHUB_REPO) and the local Kiro
    # Desktop loop — no GitHub App registration required.
    ADMIN_EMAILS: str = ""
    DEMO_REPO_FULL_NAME: str = ""
    DEMO_REPO_DEPLOY_URL: str = ""
    DEMO_REPO_LOCAL_LOOP: bool = True

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()]


settings = Settings()
