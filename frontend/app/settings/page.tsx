"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { useAuth, useUser } from "@clerk/nextjs";
import Navbar from "../components/Navbar";
import { useAuthFetch } from "../lib/useAuthFetch";

const API = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api`;

interface AWSConfig {
  role_arn: string;
  external_id: string;
  connected: boolean;
}

interface GitHubConfig {
  repo_url: string;
  connected: boolean;
}

export default function SettingsPage() {
  const { user } = useUser();
  const { has } = useAuth();
  const authFetch = useAuthFetch();

  // Nimbus doesn't yet define plan slugs beyond "free" — this resolves once the
  // paid plans are configured in the Clerk Dashboard (see PIPELINE_PLAN / HANDOFF).
  const isPro = has?.({ plan: "pro" }) ?? false;

  const [awsConfig, setAwsConfig] = useState<AWSConfig>({
    role_arn: "",
    external_id: "",
    connected: false,
  });

  const [githubConfig, setGithubConfig] = useState<GitHubConfig>({
    repo_url: "",
    connected: false,
  });

  const [awsSaving, setAwsSaving] = useState(false);
  const [awsStatus, setAwsStatus] = useState<"idle" | "success" | "error">("idle");
  const [awsError, setAwsError] = useState("");

  const [githubSaving, setGithubSaving] = useState(false);
  const [githubStatus, setGithubStatus] = useState<"idle" | "success" | "error">("idle");

  const [freeTier, setFreeTier] = useState(true);

  useEffect(() => {
    const ft = localStorage.getItem("nimbus_free_tier");
    if (ft !== null) setFreeTier(JSON.parse(ft));
  }, []);

  // Check existing connection on mount
  useEffect(() => {
    const checkConnection = async () => {
      try {
        const res = await authFetch(`${API}/settings/aws`);
        if (res.ok) {
          const data = await res.json();
          setAwsConfig((prev) => ({
            ...prev,
            connected: data.connected,
            external_id: data.external_id || "",
            role_arn: data.role_arn || "",
          }));
        }
      } catch {
        // Backend may not be running
      }

      try {
        const res = await authFetch(`${API}/settings/github`);
        if (res.ok) {
          const data = await res.json();
          setGithubConfig((prev) => ({ ...prev, connected: data.connected, repo_url: data.repo_url || "" }));
        }
      } catch {
        // Backend may not be running
      }
    };
    checkConnection();
  }, []);

  const saveAWS = async () => {
    setAwsSaving(true);
    setAwsStatus("idle");
    setAwsError("");

    try {
      const res = await authFetch(`${API}/settings/aws`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role_arn: awsConfig.role_arn }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to connect");
      }

      setAwsStatus("success");
      setAwsConfig((prev) => ({ ...prev, connected: true }));
    } catch (e: unknown) {
      setAwsStatus("error");
      setAwsError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setAwsSaving(false);
    }
  };

  const saveGitHub = async () => {
    setGithubSaving(true);
    setGithubStatus("idle");

    try {
      const res = await authFetch(`${API}/settings/github`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: githubConfig.repo_url }),
      });

      if (!res.ok) throw new Error("Failed to link");

      setGithubStatus("success");
      setGithubConfig((prev) => ({ ...prev, connected: true }));
    } catch {
      setGithubStatus("error");
    } finally {
      setGithubSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-grid">
      <Navbar />

      <main className="mx-auto max-w-3xl px-6 pt-20 pb-12">
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-8"
        >
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="mt-1 text-sm text-slate-400">
            Connect your accounts to start deploying infrastructure
          </p>
        </motion.div>

        {/* User info */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.4 }}
          className="glass mb-6 rounded-xl p-6"
        >
          <div className="flex items-center gap-4">
            {user?.imageUrl && (
              <img
                src={user.imageUrl}
                alt=""
                className="h-12 w-12 rounded-full ring-2 ring-sky-500/30"
              />
            )}
            <div>
              <p className="font-medium text-white">
                {user?.fullName || user?.primaryEmailAddress?.emailAddress || "User"}
              </p>
              <p className="text-sm text-slate-400">
                {user?.primaryEmailAddress?.emailAddress}
              </p>
            </div>
          </div>
        </motion.div>

        {/* Billing & Plan */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.075, duration: 0.4 }}
          className="glass mb-6 rounded-xl p-6"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-500/10 text-lg">
                💳
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">Billing & Plan</h2>
                <p className="text-xs text-slate-500">
                  Current plan: <span className="font-medium text-slate-300">{isPro ? "Pro" : "Free"}</span>
                </p>
              </div>
            </div>
            <Link
              href="/settings/billing"
              className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white"
            >
              Manage plan
            </Link>
          </div>
        </motion.div>

        {/* AWS Credentials */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.4 }}
          className="glass mb-6 rounded-xl p-6"
        >
          <div className="mb-5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-500/10 text-lg">
                🔑
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">AWS Account</h2>
                <p className="text-xs text-slate-500">Required to deploy resources</p>
              </div>
            </div>
            {awsConfig.connected && (
              <span className="rounded-full border border-emerald-500/25 bg-emerald-500/15 px-3 py-1 text-xs font-medium text-emerald-400">
                Connected
              </span>
            )}
          </div>

          {awsConfig.connected ? (
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-4">
              <p className="text-sm text-emerald-300">Your AWS account is connected via IAM role.</p>
              <p className="mt-1 break-all font-mono text-xs text-emerald-400/80">{awsConfig.role_arn}</p>
              <button
                onClick={() => setAwsConfig((prev) => ({ ...prev, connected: false }))}
                className="mt-2 text-xs text-slate-400 underline hover:text-white transition"
              >
                Update role
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">
                  Step 1 — Your External ID
                </label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 truncate rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm font-mono text-sky-300">
                    {awsConfig.external_id || "Loading..."}
                  </code>
                  <button
                    type="button"
                    onClick={() => awsConfig.external_id && navigator.clipboard.writeText(awsConfig.external_id)}
                    className="shrink-0 rounded-lg border border-slate-600 px-3 py-2.5 text-xs font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white"
                  >
                    Copy
                  </button>
                </div>
                <p className="mt-1.5 text-xs text-slate-500">
                  You&apos;ll paste this into the CloudFormation stack in step 2.
                </p>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">
                  Step 2 — Deploy the access role
                </label>
                <a
                  href="/nimbus-cross-account-role.yaml"
                  download
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-600 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white"
                >
                  ⬇ Download CloudFormation template
                </a>
                <p className="mt-1.5 text-xs text-slate-500">
                  In the AWS Console, go to CloudFormation → Create stack → Upload this template,
                  paste your External ID from step 1 as the <span className="font-mono">ExternalId</span>{" "}
                  parameter, and deploy.
                </p>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">
                  Step 3 — Paste the Role ARN
                </label>
                <input
                  type="text"
                  value={awsConfig.role_arn}
                  onChange={(e) => setAwsConfig((prev) => ({ ...prev, role_arn: e.target.value }))}
                  placeholder="arn:aws:iam::123456789012:role/NimbusAccessRole"
                  className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none transition focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30 font-mono"
                />
                <p className="mt-1.5 text-xs text-slate-500">
                  Copy this from the stack&apos;s Outputs tab once it finishes creating.
                </p>
              </div>

              <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3">
                <p className="text-xs text-amber-300/80">
                  Nimbus never sees or stores a long-lived AWS key — it requests short-lived,
                  expiring credentials from this role only when it needs to act on your account.
                  Revoke access anytime by deleting the CloudFormation stack.
                </p>
              </div>

              {awsStatus === "error" && (
                <div className="rounded-lg bg-red-500/5 border border-red-500/20 p-3">
                  <p className="text-xs text-red-400">{awsError || "Failed to connect. Check the role ARN."}</p>
                </div>
              )}

              {awsStatus === "success" && (
                <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3">
                  <p className="text-xs text-emerald-400">AWS account connected successfully!</p>
                </div>
              )}

              <button
                onClick={saveAWS}
                disabled={awsSaving || !awsConfig.role_arn}
                className="w-full rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-500/20 transition hover:brightness-110 disabled:opacity-40"
              >
                {awsSaving ? "Connecting..." : "Connect AWS Account"}
              </button>
            </div>
          )}
        </motion.div>

        {/* GitHub Integration */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, duration: 0.4 }}
          className="glass mb-6 rounded-xl p-6"
        >
          <div className="mb-5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-500/10 text-lg">
                <svg className="h-5 w-5 text-white" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
                </svg>
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">GitHub Repository</h2>
                <p className="text-xs text-slate-500">Optional — link a repo for config file generation</p>
              </div>
            </div>
            {githubConfig.connected && (
              <span className="rounded-full border border-emerald-500/25 bg-emerald-500/15 px-3 py-1 text-xs font-medium text-emerald-400">
                Linked
              </span>
            )}
          </div>

          {githubConfig.connected ? (
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-4">
              <p className="text-sm text-emerald-300 font-mono">{githubConfig.repo_url}</p>
              <button
                onClick={() => setGithubConfig({ repo_url: "", connected: false })}
                className="mt-2 text-xs text-slate-400 underline hover:text-white transition"
              >
                Unlink repository
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-300">
                  Repository URL
                </label>
                <input
                  type="text"
                  value={githubConfig.repo_url}
                  onChange={(e) => setGithubConfig((prev) => ({ ...prev, repo_url: e.target.value }))}
                  placeholder="https://github.com/username/repo"
                  className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none transition focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30 font-mono"
                />
              </div>

              {githubStatus === "success" && (
                <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3">
                  <p className="text-xs text-emerald-400">Repository linked!</p>
                </div>
              )}

              {githubStatus === "error" && (
                <div className="rounded-lg bg-red-500/5 border border-red-500/20 p-3">
                  <p className="text-xs text-red-400">Failed to link repository.</p>
                </div>
              )}

              <button
                onClick={saveGitHub}
                disabled={githubSaving || !githubConfig.repo_url}
                className="w-full rounded-xl border border-slate-600 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white disabled:opacity-40"
              >
                {githubSaving ? "Linking..." : "Link Repository"}
              </button>
            </div>
          )}
        </motion.div>

        {/* Preferences */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.4 }}
          className="glass rounded-xl p-6"
        >
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10 text-lg">
              ⚙️
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Preferences</h2>
              <p className="text-xs text-slate-500">Configure how Nimbus behaves</p>
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-lg bg-slate-800/50 p-4">
              <div>
                <p className="text-sm font-medium text-white">Free Tier Mode</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Restrict Architect to only recommend free-tier eligible services
                </p>
              </div>
              <label className="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  checked={freeTier}
                  onChange={(e) => {
                    setFreeTier(e.target.checked);
                    localStorage.setItem("nimbus_free_tier", JSON.stringify(e.target.checked));
                  }}
                  className="peer sr-only"
                />
                <div className="peer h-6 w-11 rounded-full bg-slate-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-slate-400 after:transition-all peer-checked:bg-sky-500 peer-checked:after:translate-x-full peer-checked:after:bg-white" />
              </label>
            </div>

            <div className="rounded-lg bg-slate-800/50 p-4">
              <p className="text-sm font-medium text-white">Bodyguard Auto-stop</p>
              <p className="text-xs text-slate-500 mt-0.5">
                Always on — Bodyguard automatically stops Nimbus-managed instances with &lt;5% CPU for 30+ minutes
                and alerts you before it does. There&apos;s no off switch yet.
              </p>
            </div>
          </div>
        </motion.div>
      </main>
    </div>
  );
}
