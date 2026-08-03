"use client";

import { useState, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useAuth, useUser } from "@clerk/nextjs";
import {
  Key,
  CloudArrowUp,
  GithubLogo,
  SlidersHorizontal,
  CreditCard,
  UserCircle,
  Check,
  X,
  Eye,
  EyeSlash,
  Cpu,
  ArrowCounterClockwise,
} from "@phosphor-icons/react";
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

interface ApiKeyStatus {
  source: "user" | "operator" | null;
  configured: boolean;
  masked: string | null;
}

const API_KEY_PROVIDERS = [
  { id: "groq", label: "Groq", hint: "console.groq.com/keys" },
  { id: "openrouter", label: "OpenRouter", hint: "openrouter.ai/keys" },
  { id: "huggingface", label: "HuggingFace", hint: "huggingface.co/settings/tokens" },
] as const;

interface ModelStatus {
  model: string;
  is_custom: boolean;
  default: string;
}

type Category = "profile" | "billing" | "aws" | "github" | "api-keys" | "models" | "preferences";

const CATEGORIES: { id: Category; label: string; icon: React.ElementType }[] = [
  { id: "profile", label: "Profile", icon: UserCircle },
  { id: "billing", label: "Billing & Plan", icon: CreditCard },
  { id: "aws", label: "AWS Account", icon: CloudArrowUp },
  { id: "github", label: "GitHub", icon: GithubLogo },
  { id: "api-keys", label: "API Keys", icon: Key },
  { id: "models", label: "Model Configurations", icon: Cpu },
  { id: "preferences", label: "Preferences", icon: SlidersHorizontal },
];

export default function SettingsPage() {
  const { user } = useUser();
  const { has } = useAuth();
  const authFetch = useAuthFetch();

  const [active, setActive] = useState<Category>("profile");

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

  const [apiKeys, setApiKeys] = useState<Record<string, ApiKeyStatus>>({});
  const [apiKeyDrafts, setApiKeyDrafts] = useState<Record<string, string>>({});
  const [apiKeyEditing, setApiKeyEditing] = useState<Record<string, boolean>>({});
  const [apiKeyReveal, setApiKeyReveal] = useState<Record<string, boolean>>({});
  const [apiKeySaving, setApiKeySaving] = useState<string | null>(null);
  const [apiKeyError, setApiKeyError] = useState<Record<string, string>>({});

  const [models, setModels] = useState<Record<string, ModelStatus>>({});
  const [modelDrafts, setModelDrafts] = useState<Record<string, string>>({});
  const [modelSaving, setModelSaving] = useState<string | null>(null);
  const [modelError, setModelError] = useState<Record<string, string>>({});

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

      try {
        const res = await authFetch(`${API}/settings/api-keys`);
        if (res.ok) setApiKeys(await res.json());
      } catch {
        // Backend may not be running
      }

      try {
        const res = await authFetch(`${API}/settings/models`);
        if (res.ok) setModels(await res.json());
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

  const unlinkGitHub = async () => {
    setGithubSaving(true);
    setGithubStatus("idle");
    try {
      const res = await authFetch(`${API}/settings/github`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to unlink");
      setGithubConfig({ repo_url: "", connected: false });
    } catch {
      setGithubStatus("error");
    } finally {
      setGithubSaving(false);
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

  const saveApiKey = async (provider: string) => {
    const key = (apiKeyDrafts[provider] || "").trim();
    if (!key) return;

    setApiKeySaving(provider);
    setApiKeyError((prev) => ({ ...prev, [provider]: "" }));

    try {
      const res = await authFetch(`${API}/settings/api-keys/${provider}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to save key");
      }
      const data = await res.json();
      setApiKeys((prev) => ({ ...prev, ...data }));
      setApiKeyDrafts((prev) => ({ ...prev, [provider]: "" }));
      setApiKeyEditing((prev) => ({ ...prev, [provider]: false }));
    } catch (e: unknown) {
      setApiKeyError((prev) => ({
        ...prev,
        [provider]: e instanceof Error ? e.message : "Failed to save key",
      }));
    } finally {
      setApiKeySaving(null);
    }
  };

  const deleteApiKey = async (provider: string) => {
    setApiKeySaving(provider);
    try {
      const res = await authFetch(`${API}/settings/api-keys/${provider}`, { method: "DELETE" });
      if (res.ok) {
        const data = await res.json();
        setApiKeys((prev) => ({ ...prev, ...data }));
      }
    } finally {
      setApiKeySaving(null);
    }
  };

  const saveModel = async (provider: string) => {
    // Falls back to the displayed (possibly default-prefilled) value, not just
    // what the user actively typed — otherwise Save stays disabled/no-ops when
    // the field still shows the default and nothing has been edited yet.
    const model = (modelDrafts[provider] ?? models[provider]?.model ?? "").trim();
    if (!model) return;

    setModelSaving(provider);
    setModelError((prev) => ({ ...prev, [provider]: "" }));

    try {
      const res = await authFetch(`${API}/settings/models/${provider}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to save model");
      }
      const data = await res.json();
      setModels((prev) => ({ ...prev, ...data }));
      // Clear the draft by DELETING the key, not setting "" — displayValue's
      // `modelDrafts[id] ?? status?.model` only falls through on null/undefined,
      // so "" would pin the input empty (default only visible as a placeholder)
      // instead of showing the value that was just saved.
      setModelDrafts((prev) => {
        const next = { ...prev };
        delete next[provider];
        return next;
      });
    } catch (e: unknown) {
      setModelError((prev) => ({
        ...prev,
        [provider]: e instanceof Error ? e.message : "Failed to save model",
      }));
    } finally {
      setModelSaving(null);
    }
  };

  const resetModel = async (provider: string) => {
    setModelSaving(provider);
    try {
      const res = await authFetch(`${API}/settings/models/${provider}`, { method: "DELETE" });
      if (res.ok) {
        const data = await res.json();
        setModels((prev) => ({ ...prev, ...data }));
        // Discard any unsaved edit in the field — otherwise it'd keep showing
        // typed-but-never-saved text instead of the default that was just restored.
        setModelDrafts((prev) => {
          const next = { ...prev };
          delete next[provider];
          return next;
        });
      }
    } finally {
      setModelSaving(null);
    }
  };

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="mx-auto max-w-5xl px-6 pt-20 pb-12">
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-8"
        >
          <h1 className="font-display text-2xl font-bold text-white">Settings</h1>
          <p className="mt-1 text-sm text-slate-400">
            Connect your accounts to start deploying infrastructure
          </p>
        </motion.div>

        <div className="flex flex-col gap-6 md:flex-row">
          {/* Sidebar */}
          <nav className="shrink-0 md:w-56">
            <ul className="flex gap-1.5 overflow-x-auto md:flex-col md:overflow-visible">
              {CATEGORIES.map((cat) => {
                const Icon = cat.icon;
                const isActive = active === cat.id;
                return (
                  <li key={cat.id} className="shrink-0 md:shrink">
                    <button
                      onClick={() => setActive(cat.id)}
                      className={`flex w-full items-center gap-2.5 whitespace-nowrap rounded-lg border-l-2 px-3 py-2.5 text-left text-sm font-medium transition-colors duration-150 ${
                        isActive
                          ? "border-ion-400 bg-slate-800/60 text-white"
                          : "border-transparent text-slate-400 hover:bg-slate-800/30 hover:text-slate-200"
                      }`}
                    >
                      <Icon
                        weight={isActive ? "fill" : "regular"}
                        className={`h-4 w-4 shrink-0 ${isActive ? "text-ion-400" : "text-slate-500"}`}
                      />
                      {cat.label}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>

          {/* Content */}
          <div className="min-w-0 flex-1">
            <AnimatePresence mode="wait">
              <motion.div
                key={active}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.18, ease: [0.23, 1, 0.32, 1] }}
                className="glass rounded-xl p-6"
              >
                {active === "profile" && (
                  <div className="flex items-center gap-4">
                    {user?.imageUrl && (
                      <img
                        src={user.imageUrl}
                        alt=""
                        className="h-12 w-12 rounded-full ring-2 ring-ion-500/30"
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
                )}

                {active === "billing" && (
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-base font-semibold text-white">Billing & Plan</h2>
                      <p className="text-xs text-slate-500">
                        Current plan: <span className="font-medium text-slate-300">{isPro ? "Pro" : "Free"}</span>
                      </p>
                    </div>
                    <Link
                      href="/settings/billing"
                      className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white"
                    >
                      Manage plan
                    </Link>
                  </div>
                )}

                {active === "aws" && (
                  <>
                    <div className="mb-5 flex items-center justify-between">
                      <div>
                        <h2 className="text-base font-semibold text-white">AWS Account</h2>
                        <p className="text-xs text-slate-500">Required to deploy resources</p>
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
                            <code className="flex-1 truncate rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm font-mono text-ion-300">
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
                            className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none transition focus:border-ion-500 focus:ring-1 focus:ring-ion-500/30 font-mono"
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
                          className="btn-ion w-full rounded-xl py-2.5 text-sm font-semibold text-white disabled:opacity-40"
                        >
                          {awsSaving ? "Connecting..." : "Connect AWS Account"}
                        </button>
                      </div>
                    )}
                  </>
                )}

                {active === "github" && (
                  <>
                    <div className="mb-5 flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <GithubLogo weight="fill" className="h-4 w-4 shrink-0 text-slate-400" />
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
                          onClick={unlinkGitHub}
                          disabled={githubSaving}
                          className="mt-2 text-xs text-slate-400 underline hover:text-white transition disabled:opacity-50"
                        >
                          {githubSaving ? "Unlinking..." : "Unlink repository"}
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
                            className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none transition focus:border-ion-500 focus:ring-1 focus:ring-ion-500/30 font-mono"
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
                  </>
                )}

                {active === "api-keys" && (
                  <>
                    <div className="mb-5">
                      <h2 className="text-base font-semibold text-white">API Keys</h2>
                      <p className="text-xs text-slate-500">
                        Bring your own key per provider so your chats run on your own quota instead of
                        Nimbus&apos;s shared one. Keys are encrypted at rest and never shown again after saving.
                      </p>
                    </div>

                    <div className="space-y-3">
                      {API_KEY_PROVIDERS.map(({ id, label, hint }) => {
                        const status = apiKeys[id];
                        const editing = apiKeyEditing[id] ?? false;
                        const reveal = apiKeyReveal[id] ?? false;
                        const saving = apiKeySaving === id;
                        const error = apiKeyError[id];

                        return (
                          <div key={id} className="rounded-lg bg-slate-800/50 p-4">
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="text-sm font-medium text-white">{label}</p>
                                <p className="text-xs text-slate-500">{hint}</p>
                              </div>
                              {status?.source === "user" && (
                                <span className="flex shrink-0 items-center gap-1 rounded-full border border-frost-500/25 bg-frost-500/15 px-2.5 py-1 text-xs font-medium text-frost-300">
                                  <Check weight="bold" className="h-3 w-3" /> Your key
                                </span>
                              )}
                              {status?.source === "operator" && (
                                <span className="shrink-0 rounded-full border border-slate-600 px-2.5 py-1 text-xs font-medium text-slate-400">
                                  Shared key
                                </span>
                              )}
                              {status && !status.configured && (
                                <span className="shrink-0 rounded-full border border-slate-700 px-2.5 py-1 text-xs font-medium text-slate-500">
                                  Not configured
                                </span>
                              )}
                            </div>

                            {status?.source === "user" && !editing ? (
                              <div className="mt-3 flex items-center gap-2">
                                <code className="flex-1 truncate rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs font-mono text-slate-400">
                                  {status.masked}
                                </code>
                                <button
                                  onClick={() => setApiKeyEditing((prev) => ({ ...prev, [id]: true }))}
                                  className="shrink-0 rounded-lg border border-slate-600 px-3 py-2 text-xs font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white"
                                >
                                  Replace
                                </button>
                                <button
                                  onClick={() => deleteApiKey(id)}
                                  disabled={saving}
                                  className="shrink-0 rounded-lg border border-red-900/50 px-3 py-2 text-xs font-medium text-red-400 transition hover:bg-red-500/10 disabled:opacity-40"
                                >
                                  <X weight="bold" className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            ) : (
                              <div className="mt-3 flex items-center gap-2">
                                <div className="relative flex-1">
                                  <input
                                    type={reveal ? "text" : "password"}
                                    value={apiKeyDrafts[id] || ""}
                                    onChange={(e) =>
                                      setApiKeyDrafts((prev) => ({ ...prev, [id]: e.target.value }))
                                    }
                                    placeholder={`Paste your ${label} key`}
                                    className="w-full rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 pr-9 text-xs text-white placeholder-slate-500 outline-none transition focus:border-ion-500 focus:ring-1 focus:ring-ion-500/30 font-mono"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => setApiKeyReveal((prev) => ({ ...prev, [id]: !reveal }))}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                                    tabIndex={-1}
                                  >
                                    {reveal ? <EyeSlash className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                  </button>
                                </div>
                                <button
                                  onClick={() => saveApiKey(id)}
                                  disabled={saving || !(apiKeyDrafts[id] || "").trim()}
                                  className="btn-ion shrink-0 rounded-lg px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"
                                >
                                  {saving ? "Saving..." : "Save"}
                                </button>
                                {editing && (
                                  <button
                                    onClick={() => setApiKeyEditing((prev) => ({ ...prev, [id]: false }))}
                                    className="shrink-0 text-xs text-slate-500 hover:text-slate-300"
                                  >
                                    Cancel
                                  </button>
                                )}
                              </div>
                            )}
                            {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}

                {active === "models" && (
                  <>
                    <div className="mb-5">
                      <h2 className="text-base font-semibold text-white">Model Configurations</h2>
                      <p className="text-xs text-slate-500">
                        Override which model each provider runs on. Every Nimbus agent depends on
                        tool/function calling — pick a model that supports it, or agents will silently fail.
                      </p>
                    </div>

                    <div className="space-y-3">
                      {API_KEY_PROVIDERS.map(({ id, label }) => {
                        const status = models[id];
                        const saving = modelSaving === id;
                        const error = modelError[id];
                        // The field is prefilled with the current effective model (default or
                        // custom) even before the user edits it — Save/disabled logic must key
                        // off that displayed value, not only what's actively been typed.
                        const displayValue = modelDrafts[id] ?? status?.model ?? "";

                        return (
                          <div key={id} className="rounded-lg bg-slate-800/50 p-4">
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="text-sm font-medium text-white">{label}</p>
                                <p className="text-xs text-slate-500">
                                  Default: <span className="font-mono">{status?.default ?? "…"}</span>
                                </p>
                              </div>
                              {status?.is_custom && (
                                <span className="flex shrink-0 items-center gap-1 rounded-full border border-frost-500/25 bg-frost-500/15 px-2.5 py-1 text-xs font-medium text-frost-300">
                                  <Check weight="bold" className="h-3 w-3" /> Custom
                                </span>
                              )}
                            </div>

                            <div className="mt-3 flex items-center gap-2">
                              <input
                                type="text"
                                value={displayValue}
                                onChange={(e) => setModelDrafts((prev) => ({ ...prev, [id]: e.target.value }))}
                                placeholder={status?.default}
                                className="w-full rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs text-white placeholder-slate-500 outline-none transition focus:border-ion-500 focus:ring-1 focus:ring-ion-500/30 font-mono"
                              />
                              <button
                                onClick={() => saveModel(id)}
                                disabled={saving || !displayValue.trim()}
                                className="btn-ion shrink-0 rounded-lg px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"
                              >
                                {saving ? "Saving..." : "Save"}
                              </button>
                              {status?.is_custom && (
                                <button
                                  onClick={() => resetModel(id)}
                                  disabled={saving}
                                  title="Reset to default"
                                  className="shrink-0 rounded-lg border border-slate-600 p-2 text-slate-300 transition hover:bg-slate-800 hover:text-white disabled:opacity-40"
                                >
                                  <ArrowCounterClockwise className="h-3.5 w-3.5" />
                                </button>
                              )}
                            </div>
                            {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}

                {active === "preferences" && (
                  <>
                    <div className="mb-5">
                      <h2 className="text-base font-semibold text-white">Preferences</h2>
                      <p className="text-xs text-slate-500">Configure how Nimbus behaves</p>
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
                          <div className="peer h-6 w-11 rounded-full bg-slate-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-slate-400 after:transition-all peer-checked:bg-ion-500 peer-checked:after:translate-x-full peer-checked:after:bg-white" />
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
                  </>
                )}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </main>
    </div>
  );
}
