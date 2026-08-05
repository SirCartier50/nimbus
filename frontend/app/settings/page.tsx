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
  Eye,
  EyeSlash,
  Cpu,
  ArrowCounterClockwise,
  PencilSimple,
  Trash,
  Plus,
  WarningCircle,
  CaretDown,
} from "@phosphor-icons/react";
import Navbar from "../components/Navbar";
import { useAuthFetch } from "../lib/useAuthFetch";

const API = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api`;

// Shared row/control chrome — a single flat panel per tab, divided into hairline
// rows instead of a stack of nested boxes-within-a-box. Inspired by ChatGPT's
// settings modal: labels + controls sit directly on the panel, separated by a
// 1px divider, and colored "notice" boxes are replaced with inline colored text.
const ROW = "flex items-center justify-between gap-4 py-4 border-b border-white/[0.06] last:border-0";
const INPUT =
  "w-full rounded-lg border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-white placeholder-slate-500 outline-none transition focus:border-ion-500/60 focus:ring-1 focus:ring-ion-500/25 font-mono";
const ICON_BTN =
  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-white/[0.06] hover:text-white";
const LABEL = "text-xs font-medium uppercase tracking-wide text-slate-500";

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

  // Adding a brand-new key is a separate, explicit flow from editing one that
  // already exists — a single "+ Add key" action instead of a permanently-open
  // input under every provider, so existing rows stay clean (masked value +
  // edit/delete) and never get disturbed by an in-progress add.
  const [addingKey, setAddingKey] = useState(false);
  const [addProvider, setAddProvider] = useState<string | null>(null);

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

  // Providers the user hasn't brought their own key for yet — the only ones
  // selectable from the "+ Add key" flow. Replacing an existing user key goes
  // through the per-row Edit action instead, not this list.
  const addableProviders = API_KEY_PROVIDERS.filter((p) => apiKeys[p.id]?.source !== "user");

  const startAddKey = (providerId?: string) => {
    const target = providerId ?? addableProviders[0]?.id;
    if (!target) return;
    setAddProvider(target);
    setAddingKey(true);
    setApiKeyError((prev) => ({ ...prev, [target]: "" }));
  };

  const cancelAddKey = () => {
    if (addProvider) {
      setApiKeyDrafts((prev) => ({ ...prev, [addProvider]: "" }));
    }
    setAddingKey(false);
    setAddProvider(null);
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
      if (addingKey && addProvider === provider) {
        setAddingKey(false);
        setAddProvider(null);
      }
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
            <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
              {CATEGORIES.map((cat) => {
                const Icon = cat.icon;
                const isActive = active === cat.id;
                return (
                  <li key={cat.id} className="shrink-0 md:shrink">
                    <button
                      onClick={() => setActive(cat.id)}
                      className={`flex w-full items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2.5 text-left text-sm font-medium transition-colors duration-150 ${
                        isActive
                          ? "bg-white/[0.08] text-white"
                          : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200"
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
                className="glass rounded-xl px-6"
              >
                {active === "profile" && (
                  <div className={ROW}>
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
                  </div>
                )}

                {active === "billing" && (
                  <div className={ROW}>
                    <div>
                      <h2 className="text-base font-semibold text-white">Billing & Plan</h2>
                      <p className="text-xs text-slate-500">
                        Current plan: <span className="font-medium text-slate-300">{isPro ? "Pro" : "Free"}</span>
                      </p>
                    </div>
                    <Link
                      href="/settings/billing"
                      className="shrink-0 rounded-lg border border-white/10 px-4 py-2 text-sm font-medium text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
                    >
                      Manage plan
                    </Link>
                  </div>
                )}

                {active === "aws" && (
                  <>
                    <div className={ROW}>
                      <div>
                        <h2 className="text-base font-semibold text-white">AWS Account</h2>
                        <p className="text-xs text-slate-500">Required to deploy resources</p>
                      </div>
                      {awsConfig.connected && (
                        <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-emerald-400">
                          <Check weight="bold" className="h-3.5 w-3.5" /> Connected
                        </span>
                      )}
                    </div>

                    {awsConfig.connected ? (
                      <div className={ROW}>
                        <div className="min-w-0">
                          <p className="text-sm text-slate-300">Your AWS account is connected via IAM role.</p>
                          <p className="mt-1 truncate font-mono text-xs text-slate-500">{awsConfig.role_arn}</p>
                        </div>
                        <button
                          onClick={() => setAwsConfig((prev) => ({ ...prev, connected: false }))}
                          className="shrink-0 text-xs text-slate-400 underline underline-offset-2 hover:text-white transition"
                        >
                          Update role
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className={`${ROW} flex-col items-stretch`}>
                          <label className={`mb-2 block ${LABEL}`}>Step 1 — Your External ID</label>
                          <div className="flex items-center gap-2">
                            <code className="flex-1 truncate rounded-lg border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm font-mono text-ion-300">
                              {awsConfig.external_id || "Loading..."}
                            </code>
                            <button
                              type="button"
                              onClick={() => awsConfig.external_id && navigator.clipboard.writeText(awsConfig.external_id)}
                              className="shrink-0 rounded-lg border border-white/10 px-3 py-2.5 text-xs font-medium text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
                            >
                              Copy
                            </button>
                          </div>
                          <p className="mt-1.5 text-xs text-slate-500">
                            You&apos;ll paste this into the CloudFormation stack in step 2.
                          </p>
                        </div>

                        <div className={`${ROW} flex-col items-stretch`}>
                          <label className={`mb-2 block ${LABEL}`}>Step 2 — Deploy the access role</label>
                          <a
                            href="/nimbus-cross-account-role.yaml"
                            download
                            className="inline-flex w-fit items-center gap-2 rounded-lg border border-white/10 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
                          >
                            ⬇ Download CloudFormation template
                          </a>
                          <p className="mt-1.5 text-xs text-slate-500">
                            In the AWS Console, go to CloudFormation → Create stack → Upload this template,
                            paste your External ID from step 1 as the <span className="font-mono">ExternalId</span>{" "}
                            parameter, and deploy.
                          </p>
                        </div>

                        <div className={`${ROW} flex-col items-stretch`}>
                          <label className={`mb-2 block ${LABEL}`}>Step 3 — Paste the Role ARN</label>
                          <input
                            type="text"
                            value={awsConfig.role_arn}
                            onChange={(e) => setAwsConfig((prev) => ({ ...prev, role_arn: e.target.value }))}
                            placeholder="arn:aws:iam::123456789012:role/NimbusAccessRole"
                            className={INPUT}
                          />
                          <p className="mt-1.5 text-xs text-slate-500">
                            Copy this from the stack&apos;s Outputs tab once it finishes creating.
                          </p>

                          <p className="mt-4 text-xs leading-relaxed text-slate-500">
                            Nimbus never sees or stores a long-lived AWS key — it requests short-lived,
                            expiring credentials from this role only when it needs to act on your account.
                            Revoke access anytime by deleting the CloudFormation stack.
                          </p>

                          {awsStatus === "error" && (
                            <p className="mt-3 flex items-center gap-1.5 text-xs text-red-400">
                              <WarningCircle weight="fill" className="h-3.5 w-3.5 shrink-0" />
                              {awsError || "Failed to connect. Check the role ARN."}
                            </p>
                          )}

                          {awsStatus === "success" && (
                            <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-400">
                              <Check weight="bold" className="h-3.5 w-3.5 shrink-0" />
                              AWS account connected successfully!
                            </p>
                          )}

                          <button
                            onClick={saveAWS}
                            disabled={awsSaving || !awsConfig.role_arn}
                            className="btn-ion mt-4 w-full rounded-xl py-2.5 text-sm font-semibold text-white disabled:opacity-40"
                          >
                            {awsSaving ? "Connecting..." : "Connect AWS Account"}
                          </button>
                        </div>
                      </>
                    )}
                  </>
                )}

                {active === "github" && (
                  <>
                    <div className={ROW}>
                      <div className="flex items-center gap-2.5">
                        <GithubLogo weight="fill" className="h-4 w-4 shrink-0 text-slate-400" />
                        <div>
                          <h2 className="text-base font-semibold text-white">GitHub Repository</h2>
                          <p className="text-xs text-slate-500">Optional — link a repo for config file generation</p>
                        </div>
                      </div>
                      {githubConfig.connected && (
                        <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-emerald-400">
                          <Check weight="bold" className="h-3.5 w-3.5" /> Linked
                        </span>
                      )}
                    </div>

                    {githubConfig.connected ? (
                      <div className={ROW}>
                        <p className="truncate text-sm font-mono text-slate-300">{githubConfig.repo_url}</p>
                        <button
                          onClick={unlinkGitHub}
                          disabled={githubSaving}
                          className="shrink-0 text-xs text-slate-400 underline underline-offset-2 hover:text-white transition disabled:opacity-50"
                        >
                          {githubSaving ? "Unlinking..." : "Unlink repository"}
                        </button>
                      </div>
                    ) : (
                      <div className={`${ROW} flex-col items-stretch`}>
                        <label className={`mb-2 block ${LABEL}`}>Repository URL</label>
                        <input
                          type="text"
                          value={githubConfig.repo_url}
                          onChange={(e) => setGithubConfig((prev) => ({ ...prev, repo_url: e.target.value }))}
                          placeholder="https://github.com/username/repo"
                          className={INPUT}
                        />

                        {githubStatus === "success" && (
                          <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-400">
                            <Check weight="bold" className="h-3.5 w-3.5 shrink-0" /> Repository linked!
                          </p>
                        )}

                        {githubStatus === "error" && (
                          <p className="mt-3 flex items-center gap-1.5 text-xs text-red-400">
                            <WarningCircle weight="fill" className="h-3.5 w-3.5 shrink-0" /> Failed to link repository.
                          </p>
                        )}

                        <button
                          onClick={saveGitHub}
                          disabled={githubSaving || !githubConfig.repo_url}
                          className="mt-4 w-full rounded-xl border border-white/10 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/[0.06] hover:text-white disabled:opacity-40"
                        >
                          {githubSaving ? "Linking..." : "Link Repository"}
                        </button>
                      </div>
                    )}
                  </>
                )}

                {active === "api-keys" && (
                  <>
                    <div className={ROW}>
                      <div>
                        <h2 className="text-base font-semibold text-white">API Keys</h2>
                        <p className="text-xs text-slate-500">
                          Bring your own key per provider so your chats run on your own quota instead of
                          Nimbus&apos;s shared one. Keys are encrypted at rest and never shown again after saving.
                        </p>
                      </div>
                      {addableProviders.length > 0 && !addingKey && (
                        <button
                          onClick={() => startAddKey()}
                          className="btn-ion flex shrink-0 items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold text-white"
                        >
                          <Plus weight="bold" className="h-3.5 w-3.5" /> Add key
                        </button>
                      )}
                    </div>

                    {/* Keys the user has brought themselves — edit or delete only,
                        never a bare input sitting open. */}
                    {API_KEY_PROVIDERS.filter((p) => apiKeys[p.id]?.source === "user").map(({ id, label, hint }) => {
                      const status = apiKeys[id];
                      const editing = apiKeyEditing[id] ?? false;
                      const reveal = apiKeyReveal[id] ?? false;
                      const saving = apiKeySaving === id;
                      const error = apiKeyError[id];

                      return (
                        <div key={id} className={`${ROW} flex-col items-stretch`}>
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-sm font-medium text-white">{label}</p>
                              <p className="text-xs text-slate-500">{hint}</p>
                            </div>
                            {!editing && (
                              <div className="flex shrink-0 items-center gap-1">
                                <span className="mr-1 flex items-center gap-1 text-xs font-medium text-frost-300">
                                  <Check weight="bold" className="h-3 w-3" /> Your key
                                </span>
                                <button
                                  onClick={() => setApiKeyEditing((prev) => ({ ...prev, [id]: true }))}
                                  className={ICON_BTN}
                                  title="Edit key"
                                >
                                  <PencilSimple className="h-4 w-4" />
                                </button>
                                <button
                                  onClick={() => deleteApiKey(id)}
                                  disabled={saving}
                                  className={`${ICON_BTN} hover:bg-red-500/10 hover:text-red-400 disabled:opacity-40`}
                                  title="Delete key"
                                >
                                  <Trash className="h-4 w-4" />
                                </button>
                              </div>
                            )}
                          </div>

                          {!editing ? (
                            <code className="mt-2 w-fit rounded-md bg-white/[0.03] px-2.5 py-1 text-xs font-mono text-slate-500">
                              {status?.masked}
                            </code>
                          ) : (
                            <div className="mt-3 flex items-center gap-2">
                              <div className="relative flex-1">
                                <input
                                  type={reveal ? "text" : "password"}
                                  value={apiKeyDrafts[id] || ""}
                                  onChange={(e) => setApiKeyDrafts((prev) => ({ ...prev, [id]: e.target.value }))}
                                  placeholder={`Paste your new ${label} key`}
                                  autoFocus
                                  className={`${INPUT} pr-9 py-2 text-xs`}
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
                              <button
                                onClick={() => {
                                  setApiKeyEditing((prev) => ({ ...prev, [id]: false }));
                                  setApiKeyDrafts((prev) => ({ ...prev, [id]: "" }));
                                }}
                                className="shrink-0 text-xs text-slate-500 hover:text-slate-300"
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                          {error && (
                            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-red-400">
                              <WarningCircle weight="fill" className="h-3.5 w-3.5 shrink-0" /> {error}
                            </p>
                          )}
                        </div>
                      );
                    })}

                    {/* New key flow — explicit provider picker, only offered for
                        providers that don't already have a user key. */}
                    {addingKey && addProvider && (
                      <div className={`${ROW} flex-col items-stretch`}>
                        <div className="flex items-center gap-2">
                          <div className="relative">
                            <select
                              value={addProvider}
                              onChange={(e) => setAddProvider(e.target.value)}
                              className="appearance-none rounded-lg border border-white/10 bg-white/[0.03] py-2 pl-3 pr-8 text-xs font-medium text-white outline-none transition focus:border-ion-500/60 focus:ring-1 focus:ring-ion-500/25"
                            >
                              {addableProviders.map((p) => (
                                <option key={p.id} value={p.id} className="bg-slate-900">
                                  {p.label}
                                </option>
                              ))}
                            </select>
                            <CaretDown className="pointer-events-none absolute right-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-500" />
                          </div>
                          <p className="text-xs text-slate-500">
                            {API_KEY_PROVIDERS.find((p) => p.id === addProvider)?.hint}
                          </p>
                        </div>

                        <div className="mt-3 flex items-center gap-2">
                          <div className="relative flex-1">
                            <input
                              type={apiKeyReveal[addProvider] ? "text" : "password"}
                              value={apiKeyDrafts[addProvider] || ""}
                              onChange={(e) => setApiKeyDrafts((prev) => ({ ...prev, [addProvider]: e.target.value }))}
                              placeholder={`Paste your ${API_KEY_PROVIDERS.find((p) => p.id === addProvider)?.label} key`}
                              autoFocus
                              className={`${INPUT} pr-9 py-2 text-xs`}
                            />
                            <button
                              type="button"
                              onClick={() =>
                                setApiKeyReveal((prev) => ({ ...prev, [addProvider]: !prev[addProvider] }))
                              }
                              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                              tabIndex={-1}
                            >
                              {apiKeyReveal[addProvider] ? <EyeSlash className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                          </div>
                          <button
                            onClick={() => saveApiKey(addProvider)}
                            disabled={apiKeySaving === addProvider || !(apiKeyDrafts[addProvider] || "").trim()}
                            className="btn-ion shrink-0 rounded-lg px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"
                          >
                            {apiKeySaving === addProvider ? "Saving..." : "Save"}
                          </button>
                          <button onClick={cancelAddKey} className="shrink-0 text-xs text-slate-500 hover:text-slate-300">
                            Cancel
                          </button>
                        </div>
                        {apiKeyError[addProvider] && (
                          <p className="mt-1.5 flex items-center gap-1.5 text-xs text-red-400">
                            <WarningCircle weight="fill" className="h-3.5 w-3.5 shrink-0" /> {apiKeyError[addProvider]}
                          </p>
                        )}
                      </div>
                    )}

                    {/* Providers not backed by a user key yet — status only. Whichever
                        provider is mid-add already has a row in the form above it. */}
                    {API_KEY_PROVIDERS.filter(
                      (p) => apiKeys[p.id]?.source !== "user" && !(addingKey && addProvider === p.id)
                    ).map(({ id, label, hint }) => {
                      const status = apiKeys[id];
                      return (
                        <div key={id} className={ROW}>
                          <div>
                            <p className="text-sm font-medium text-slate-300">{label}</p>
                            <p className="text-xs text-slate-500">{hint}</p>
                          </div>
                          <div className="flex shrink-0 items-center gap-3">
                            <span className="text-xs font-medium text-slate-500">
                              {status?.source === "operator" ? "Shared key" : "Not configured"}
                            </span>
                            {!(addingKey && addProvider === id) && (
                              <button
                                onClick={() => startAddKey(id)}
                                className="text-xs font-medium text-ion-400 hover:text-ion-300"
                              >
                                Use your own
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}

                {active === "models" && (
                  <>
                    <div className={ROW}>
                      <div>
                        <h2 className="text-base font-semibold text-white">Model Configurations</h2>
                        <p className="text-xs text-slate-500">
                          Override which model each provider runs on. Every Nimbus agent depends on
                          tool/function calling — pick a model that supports it, or agents will silently fail.
                        </p>
                      </div>
                    </div>

                    {API_KEY_PROVIDERS.map(({ id, label }) => {
                      const status = models[id];
                      const saving = modelSaving === id;
                      const error = modelError[id];
                      // The field is prefilled with the current effective model (default or
                      // custom) even before the user edits it — Save/disabled logic must key
                      // off that displayed value, not only what's actively been typed.
                      const displayValue = modelDrafts[id] ?? status?.model ?? "";

                      return (
                        <div key={id} className={`${ROW} flex-col items-stretch`}>
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-sm font-medium text-white">{label}</p>
                              <p className="text-xs text-slate-500">
                                Default: <span className="font-mono">{status?.default ?? "…"}</span>
                              </p>
                            </div>
                            {status?.is_custom && (
                              <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-frost-300">
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
                              className={`${INPUT} py-2 text-xs`}
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
                                className={ICON_BTN}
                              >
                                <ArrowCounterClockwise className="h-4 w-4" />
                              </button>
                            )}
                          </div>
                          {error && (
                            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-red-400">
                              <WarningCircle weight="fill" className="h-3.5 w-3.5 shrink-0" /> {error}
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </>
                )}

                {active === "preferences" && (
                  <>
                    <div className={ROW}>
                      <div>
                        <h2 className="text-base font-semibold text-white">Preferences</h2>
                        <p className="text-xs text-slate-500">Configure how Nimbus behaves</p>
                      </div>
                    </div>

                    <div className={ROW}>
                      <div>
                        <p className="text-sm font-medium text-white">Free Tier Mode</p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          Restrict Architect to only recommend free-tier eligible services
                        </p>
                      </div>
                      <label className="relative inline-flex shrink-0 cursor-pointer items-center">
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

                    <div className={ROW}>
                      <div>
                        <p className="text-sm font-medium text-white">Bodyguard Auto-stop</p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          Always on — Bodyguard automatically stops Nimbus-managed instances with &lt;5% CPU for 30+
                          minutes and alerts you before it does. There&apos;s no off switch yet.
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
