"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Navbar from "../components/Navbar";
import AWSGate from "../components/AWSGate";
import { useAuthFetch } from "../lib/useAuthFetch";

const API = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api`;

// ── Types ─────────────────────────────────────────────────────────────────

interface Message {
  role: "user" | "assistant";
  content: string;
  awaiting_confirmation?: boolean;
  plan?: Plan;
  execution_results?: ExecResult[];
  generated_files?: Record<string, string>;
  activityLog?: ActivityEntry[];
  timestamp: number;
}

interface Plan {
  explanation: string;
  plan: PlanStep[];
  cost_warning: string;
  estimated_monthly_cost: string;
}

interface PlanStep {
  step: number;
  action: string;
  description: string;
  params?: Record<string, string>;
}

interface ExecResult {
  success: boolean;
  resource_type: string;
  resource_id?: string;
  message?: string;
  error?: string;
  description?: string;
  step?: number;
}

// The final turn payload — identical shape from /chat and /chat/stream's final event.
interface TurnPayload {
  session_id: string;
  content: string;
  awaiting_confirmation?: boolean;
  plan?: Plan;
  execution_results?: ExecResult[];
  generated_files?: Record<string, string>;
}

interface ActivityEntry {
  timestamp: number;
  // A pipeline stage streamed live from the backend (requirements / architect /
  // validate / finalize / executor / cancel), or "system" for client-side notes.
  agent: string;
  message: string;
  type: "info" | "success" | "error" | "thinking";
}

// ── Activity Trace ────────────────────────────────────────────────────────
// A small collapsible trace under an assistant reply showing what the agents
// did to produce it. The entries are REAL: they arrive live over SSE as each
// LangGraph node finishes (`/api/chat/stream`), not reconstructed client-side.

function ActivityTrace({ entries }: { entries: ActivityEntry[] }) {
  const [open, setOpen] = useState(false);

  const agentColor = (agent: string) => {
    switch (agent) {
      case "requirements":
      case "architect":
      case "validate":
      case "finalize": return "text-ion-400";
      case "executor": return "text-amber-400";
      case "bodyguard": return "text-emerald-400";
      default: return "text-slate-500";
    }
  };

  const typeIcon = (type: string) => {
    switch (type) {
      case "success": return "✓";
      case "error": return "✗";
      case "thinking": return "◌";
      default: return "›";
    }
  };

  const typeColor = (type: string) => {
    switch (type) {
      case "success": return "text-emerald-400";
      case "error": return "text-red-400";
      case "thinking": return "text-ion-400";
      default: return "text-slate-500";
    }
  };

  if (entries.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-slate-500 transition hover:text-slate-300"
      >
        <svg
          className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
        {entries.length === 1 ? "1 step" : `${entries.length} steps`}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-1.5 rounded-lg bg-slate-900/50 p-3 font-mono text-xs">
              {entries.map((entry, i) => (
                <div key={i} className="flex gap-2 leading-relaxed">
                  <span className={`shrink-0 ${typeColor(entry.type)}`}>{typeIcon(entry.type)}</span>
                  <span className={`shrink-0 ${agentColor(entry.agent)}`}>[{entry.agent}]</span>
                  <span className={entry.type === "error" ? "text-red-300" : "text-slate-400"}>
                    {entry.message}
                  </span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Plan Card ─────────────────────────────────────────────────────────────

function PlanCard({
  plan,
  onConfirm,
  onDecline,
  disabled,
}: {
  plan: Plan;
  onConfirm: () => void;
  onDecline: () => void;
  disabled: boolean;
}) {
  const ActionIcon = ({ action }: { action: string }) => {
    if (action.includes("ec2")) return <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg>;
    if (action.includes("s3")) return <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" /><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" /></svg>;
    if (action.includes("dynamo")) return <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path d="M4 7v10c0 2.21 3.58 4 8 4s8-1.79 8-4V7" /><ellipse cx="12" cy="7" rx="8" ry="4" /><path d="M4 12c0 2.21 3.58 4 8 4s8-1.79 8-4" /></svg>;
    if (action.includes("lambda")) return <span className="text-xs font-bold font-mono">fn</span>;
    return <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z" /></svg>;
  };

  return (
    <div className="mt-3 rounded-xl border border-ion-500/20 bg-ion-500/5 p-4">
      <p className="mb-3 text-sm text-slate-300">{plan.explanation}</p>

      <div className="space-y-2">
        {plan.plan.map((step) => (
          <div key={step.step} className="flex items-start gap-3 rounded-lg bg-slate-800/50 p-3">
            <span className="mt-0.5 text-slate-400"><ActionIcon action={step.action} /></span>
            <div>
              <p className="text-sm font-medium text-white">{step.description}</p>
              <p className="mt-0.5 text-xs text-slate-500 font-mono">{step.action}</p>
            </div>
          </div>
        ))}
      </div>

      {/* The approval gate is where real money starts — it gets the most
          deliberate-feeling controls on the screen, not a 12px afterthought. */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-ion-500/15 pt-4">
        <p className="text-sm text-slate-400">
          Est. cost: <span className="font-medium text-white">{plan.estimated_monthly_cost}</span>
          {plan.cost_warning && (
            <span className="ml-2 text-xs text-amber-400">{plan.cost_warning}</span>
          )}
        </p>

        {!disabled && (
          <div className="flex gap-2">
            <button
              onClick={onDecline}
              className="rounded-lg border border-slate-600 px-5 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-700 active:scale-[0.97]"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="btn-ion rounded-lg px-6 py-2 text-sm font-semibold text-white"
            >
              Deploy plan
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Execution Results ─────────────────────────────────────────────────────

function ResultsCard({ results }: { results: ExecResult[] }) {
  return (
    <div className="mt-3 space-y-2">
      {results.map((r, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 rounded-lg p-3 text-sm ${
            r.success
              ? "border border-emerald-500/20 bg-emerald-500/5 text-emerald-300"
              : "border border-red-500/20 bg-red-500/5 text-red-300"
          }`}
        >
          <span className="mt-0.5">{r.success ? "✓" : "✗"}</span>
          <div>
            <p>{r.success ? r.message : `${r.description}: ${r.error}`}</p>
            {r.resource_id && (
              <p className="mt-0.5 font-mono text-xs opacity-60">{r.resource_id}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Files Card ───────────────────────────────────────────────────────────

function FilesCard({ files }: { files: Record<string, string> }) {
  const download = (filename: string, content: string) => {
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAll = () => {
    Object.entries(files).forEach(([name, content]) => {
      setTimeout(() => download(name, content), 100);
    });
  };

  const fileIcon = (name: string) => {
    if (name.endsWith(".json")) return "{ }";
    if (name.endsWith(".sh")) return "#!/";
    if (name.endsWith(".yml")) return "---";
    if (name.endsWith(".py")) return "py";
    if (name.endsWith(".md")) return "md";
    return "txt";
  };

  return (
    <div className="mt-3 rounded-xl border border-ion-500/20 bg-ion-500/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="h-4 w-4 text-ion-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
          <span className="text-xs font-semibold text-ion-300">Generated Files</span>
        </div>
        <button
          onClick={downloadAll}
          className="flex items-center gap-1 rounded-lg border border-ion-500/30 bg-ion-500/10 px-3 py-1 text-xs font-medium text-ion-300 transition hover:bg-ion-500/20 active:scale-[0.97]"
        >
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
          Download All
        </button>
      </div>

      <div className="space-y-1.5">
        {Object.entries(files).map(([name, content]) => (
          <button
            key={name}
            onClick={() => download(name, content)}
            className="flex w-full items-center gap-3 rounded-lg bg-slate-800/50 p-2.5 text-left transition hover:bg-slate-800/80 active:scale-[0.98]"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-slate-700/50 font-mono text-[9px] font-bold text-ion-300">
              {fileIcon(name)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-white">{name}</p>
              <p className="text-[10px] text-slate-500">{content.length} bytes</p>
            </div>
            <svg className="h-3.5 w-3.5 shrink-0 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Message Bubble ────────────────────────────────────────────────────────

function MessageBubble({
  msg,
  onConfirm,
  onDecline,
  isLatest,
  loading,
  delay = 0,
}: {
  msg: Message;
  onConfirm: () => void;
  onDecline: () => void;
  isLatest: boolean;
  loading: boolean;
  delay?: number;
}) {
  const isUser = msg.role === "user";

  // Parse bold markdown
  const formatText = (text: string) =>
    text.split("\n").map((line, i) => {
      const parts = line.split(/\*\*(.*?)\*\*/g);
      return (
        <span key={i}>
          {parts.map((p, j) => (j % 2 === 1 ? <strong key={j} className="text-white">{p}</strong> : p))}
          <br />
        </span>
      );
    });

  const body = (
    <>
      {msg.plan && msg.awaiting_confirmation ? (
        <PlanCard plan={msg.plan} onConfirm={onConfirm} onDecline={onDecline} disabled={!isLatest || loading} />
      ) : msg.execution_results ? (
        <>
          <div>{formatText(msg.content)}</div>
          <ResultsCard results={msg.execution_results} />
          {msg.generated_files && Object.keys(msg.generated_files).length > 0 && (
            <FilesCard files={msg.generated_files} />
          )}
        </>
      ) : (
        <div>{formatText(msg.content)}</div>
      )}
    </>
  );

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, transform: "translateY(8px)" }}
        animate={{ opacity: 1, transform: "translateY(0px)" }}
        transition={{ duration: 0.25, delay, ease: [0.23, 1, 0.32, 1] }}
        className="flex justify-end"
      >
        <div className="max-w-[75%] rounded-2xl bg-slate-800 px-4 py-2.5 text-sm leading-relaxed text-slate-100">
          {body}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, transform: "translateY(8px)" }}
      animate={{ opacity: 1, transform: "translateY(0px)" }}
      transition={{ duration: 0.25, delay, ease: [0.23, 1, 0.32, 1] }}
      className="flex gap-3"
    >
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-ion-500 to-ion-400 text-[10px] font-bold text-white">
        N
      </div>
      <div className="min-w-0 flex-1 text-sm leading-relaxed text-slate-200">
        {msg.activityLog && <ActivityTrace entries={msg.activityLog} />}
        {body}
      </div>
    </motion.div>
  );
}

// ── Session Sidebar ──────────────────────────────────────────────────────

interface SessionSummary {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
}

const SESSIONS_PAGE_SIZE = 5;

function SessionSidebar({
  currentSessionId,
  onSelectSession,
  onNewChat,
  collapsed,
  onToggleCollapsed,
}: {
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const authFetch = useAuthFetch();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const loadFirstPage = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/sessions?limit=${SESSIONS_PAGE_SIZE}`);
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
        setHasMore(!!data.has_more);
      }
    } catch {
      // keep showing the last good list
    }
  }, [authFetch]);

  useEffect(() => {
    loadFirstPage();
    const id = setInterval(loadFirstPage, 10000);
    return () => clearInterval(id);
  }, [loadFirstPage]);

  useEffect(() => {
    loadFirstPage();
  }, [currentSessionId, loadFirstPage]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      // Titles/ids only (never message bodies), so pulling "the rest" in one shot
      // is cheap — no need for incremental/scroll-triggered paging at this scale.
      const res = await authFetch(`${API}/sessions?limit=500&offset=${sessions.length}`);
      if (res.ok) {
        const data = await res.json();
        setSessions((prev) => [...prev, ...(data.sessions || [])]);
        setHasMore(!!data.has_more);
      }
    } catch {
      // ignore
    } finally {
      setLoadingMore(false);
    }
  };

  const startRename = (s: SessionSummary) => {
    setEditingId(s.id);
    setEditValue(s.title);
  };

  const commitRename = async (id: string) => {
    const title = editValue.trim();
    setEditingId(null);
    if (!title) return;
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
    try {
      await authFetch(`${API}/sessions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
    } catch {
      // best-effort — local state already reflects the rename
    }
  };

  if (collapsed) {
    return (
      <div className="flex h-full w-14 shrink-0 flex-col items-center gap-2 bg-slate-950/30 py-3">
        <button
          onClick={onToggleCollapsed}
          title="Show conversations"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-800/60 hover:text-white active:scale-[0.95]"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </button>
        <button
          onClick={onNewChat}
          title="New chat"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-800/60 hover:text-white active:scale-[0.95]"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-64 shrink-0 flex-col bg-slate-950/30">
      <div className="flex items-center gap-2 p-3">
        <button
          onClick={onNewChat}
          className="flex flex-1 items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white active:scale-[0.98]"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New chat
        </button>
        <button
          onClick={onToggleCollapsed}
          title="Hide conversations"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-800/60 hover:text-white active:scale-[0.95]"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-3">
        <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
          Conversations
        </p>
        {sessions.length === 0 ? (
          <p className="px-1 py-2 text-xs text-slate-600">No conversations yet</p>
        ) : (
          <div className="space-y-0.5">
            <AnimatePresence initial={false}>
            {sessions.map((s) => (
              <motion.div
                key={s.id}
                layout="position"
                transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
                className={`group flex items-center gap-1 rounded-lg px-2 py-2 transition-colors ${
                  s.id === currentSessionId ? "bg-ion-500/10" : "hover:bg-slate-800/60"
                }`}
              >
                {editingId === s.id ? (
                  <input
                    autoFocus
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => commitRename(s.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitRename(s.id);
                      }
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="w-full rounded bg-slate-800 px-1.5 py-0.5 text-xs text-white outline-none ring-1 ring-ion-500/40"
                  />
                ) : (
                  <>
                    <button
                      onClick={() => onSelectSession(s.id)}
                      title={s.title}
                      className={`min-w-0 flex-1 truncate text-left text-xs active:scale-[0.98] ${
                        s.id === currentSessionId ? "text-ion-300" : "text-slate-400 group-hover:text-white"
                      }`}
                    >
                      {s.title}
                    </button>
                    <button
                      onClick={() => startRename(s)}
                      title="Rename"
                      className="hidden shrink-0 rounded p-1 text-slate-500 transition hover:text-white group-hover:block active:scale-[0.9]"
                    >
                      <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125"
                        />
                      </svg>
                    </button>
                  </>
                )}
              </motion.div>
            ))}
            </AnimatePresence>
          </div>
        )}

        {hasMore && (
          <button
            onClick={loadMore}
            disabled={loadingMore}
            className="mt-1 w-full px-2 py-1.5 text-left text-xs text-slate-500 transition hover:text-white disabled:opacity-50 active:scale-[0.98]"
          >
            {loadingMore ? "Loading..." : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Model Selector ───────────────────────────────────────────────────────

// Bedrock is intentionally absent: it silently billed the operator's AWS
// account (and its Nova Lite default underperformed on multi-step tool use).
// Only capable tool-calling models belong here — small models hallucinate
// plan execution.
const PROVIDERS = [
  { value: "openrouter", label: "OpenRouter · Llama 3.3 70B" },
  { value: "groq", label: "Groq · Llama 3.3 70B" },
  { value: "huggingface", label: "HuggingFace · DeepSeek V3" },
];

function ModelSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const current = PROVIDERS.find((p) => p.value === value) ?? PROVIDERS[0];

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-slate-400 transition-colors duration-150 hover:bg-slate-700/50 hover:text-white active:scale-[0.97]"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-ion-400" />
        {current.label}
        <svg className="h-3 w-3 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 15.75 7.5-7.5 7.5 7.5" />
        </svg>
      </button>
      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.15, ease: [0.23, 1, 0.32, 1] }}
              style={{ transformOrigin: "bottom left" }}
              className="absolute bottom-full left-0 z-50 mb-1.5 w-52 overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-xl"
            >
              {PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => {
                    onChange(p.value);
                    setOpen(false);
                  }}
                  className={`block w-full px-3 py-2 text-left text-xs transition-colors duration-150 active:scale-[0.98] ${
                    p.value === value ? "bg-ion-500/10 text-ion-300" : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

const WELCOME_MESSAGE: Message = {
  role: "assistant",
  content:
    "Hey! I'm Nimbus. Tell me what you want to build on AWS — I'll ask a few questions, design a plan with a real cost estimate, and deploy it only after you approve.",
  timestamp: Date.now(),
};

// Clickable starters instead of a wall of bold text in the first bubble.
const SUGGESTIONS = [
  "A REST API with a database",
  "A static website with file storage",
  "A serverless function that runs every hour",
];

export default function ChatPage() {
  const authFetch = useAuthFetch();
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [freeTierMode, setFreeTierMode] = useState(true);
  const [provider, setProvider] = useState("openrouter");
  // Real pipeline progress for the in-flight turn, streamed from the backend —
  // shown live next to the typing indicator, then attached to the reply's trace.
  const [liveActivity, setLiveActivity] = useState<ActivityEntry[]>([]);
  // How many of the current `messages` were bulk-loaded (session switch) rather
  // than appended live — only that leading batch gets a staggered entrance so
  // switching sessions cascades in instead of flashing all at once, while a
  // single new message during live chat still appears immediately.
  const [loadedBatchSize, setLoadedBatchSize] = useState(0);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const stored = localStorage.getItem("nimbus_free_tier");
    if (stored !== null) setFreeTierMode(JSON.parse(stored));
    const storedProvider = localStorage.getItem("nimbus_provider");
    // Ignore values that are no longer offered (e.g. "bedrock" from before its
    // removal) — otherwise a stale localStorage entry resurrects a dead provider.
    if (storedProvider && PROVIDERS.some((p) => p.value === storedProvider)) {
      setProvider(storedProvider);
    }

    // Restore whichever conversation was open before a reload — otherwise every
    // refresh silently drops back to a blank "new chat", losing the visible
    // conversation even though it's already durably saved server-side.
    const storedSessionId = localStorage.getItem("nimbus_session_id");
    if (storedSessionId) loadSession(storedSessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (sessionId) {
      localStorage.setItem("nimbus_session_id", sessionId);
    } else {
      localStorage.removeItem("nimbus_session_id");
    }
  }, [sessionId]);

  const changeProvider = (p: string) => {
    setProvider(p);
    localStorage.setItem("nimbus_provider", p);
  };

  const startNewChat = () => {
    setSessionId(null);
    setMessages([WELCOME_MESSAGE]);
    setLoadedBatchSize(0);
  };

  const loadSession = async (id: string, opts?: { force?: boolean }) => {
    if (!opts?.force && id === sessionId) return;
    try {
      const res = await authFetch(`${API}/sessions/${id}`);
      if (!res.ok) {
        // The remembered session no longer exists (deleted, or a stale id from a
        // previous account) — stop retrying it on every future reload.
        if (res.status === 404) localStorage.removeItem("nimbus_session_id");
        return;
      }
      const data = await res.json();
      const loaded = data.messages && data.messages.length > 0 ? data.messages : [WELCOME_MESSAGE];
      setSessionId(data.id);
      setMessages(loaded);
      setLoadedBatchSize(loaded.length);
    } catch {
      // ignore — keep the current conversation on screen
    }
  };

  // Parse one SSE frame stream from /chat/stream. Yields real per-agent progress
  // into the trace as each LangGraph node finishes; returns the final payload.
  const consumeStream = async (
    stream: ReadableStream<Uint8Array>,
    addActivity: (agent: string, message: string, type?: ActivityEntry["type"]) => void
  ): Promise<TurnPayload | null> => {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let final: TurnPayload | null = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!dataLine) continue;
        let evt;
        try {
          evt = JSON.parse(dataLine.slice(6));
        } catch {
          continue;
        }
        if (evt.type === "progress") {
          addActivity(evt.stage, evt.message, "thinking");
        } else if (evt.type === "error") {
          throw new Error(evt.message);
        } else if (evt.type === "final") {
          final = evt as TurnPayload;
        }
      }
    }
    return final;
  };

  const sendMessage = async (text: string, confirm?: boolean) => {
    if (!text.trim() && confirm === undefined) return;
    setLoading(true);
    setLiveActivity([]);

    // Trace for just this turn — filled by REAL progress events streamed from the
    // backend as each agent finishes, then attached to the assistant message as a
    // collapsible trail. Also mirrored into `liveActivity` so the user watches the
    // pipeline advance while waiting.
    const turnActivity: ActivityEntry[] = [];
    const addActivity = (agent: string, message: string, type: ActivityEntry["type"] = "info") => {
      turnActivity.push({ timestamp: Date.now(), agent, message, type });
      setLiveActivity([...turnActivity]);
    };

    // Add user message
    const userContent = confirm === true ? "Yes, deploy" : confirm === false ? "No, cancel" : text;
    setMessages((m) => [...m, { role: "user", content: userContent, timestamp: Date.now() }]);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";

    try {
      const body: Record<string, unknown> = {
        message: text,
        session_id: sessionId,
        free_tier_mode: freeTierMode,
        provider,
      };
      if (confirm !== undefined) body.confirm = confirm;

      const res = await authFetch(`${API}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        // 4xx bodies carry a specific, user-actionable reason (e.g. bad input,
        // rate limit); 5xx bodies may carry internal detail we shouldn't show.
        let reason = "Something went wrong on our end. Please try again.";
        if (res.status >= 400 && res.status < 500) {
          try {
            const errBody = await res.json();
            if (errBody?.detail) reason = errBody.detail;
          } catch {
            // no JSON body — keep the generic reason
          }
        }
        throw new Error(reason);
      }

      const data = res.body ? await consumeStream(res.body, addActivity) : null;
      if (!data) {
        // The stream was cut before the final event. The backend finishes and
        // persists the turn regardless of our connection, so DON'T re-send (a
        // deploy would run twice) — recover the saved result instead.
        if (sessionId) {
          await loadSession(sessionId, { force: true });
          return;
        }
        throw new Error(
          "The connection dropped mid-turn. Your request may still have completed — check your conversations."
        );
      }
      if (!sessionId) setSessionId(data.session_id);

      // Append the real outcomes to the trace (results are facts, not staging).
      data.execution_results?.forEach((r) => {
        if (r.success) {
          addActivity("executor", `${r.message}`, "success");
        } else {
          addActivity("executor", `Failed: ${r.description} — ${r.error}`, "error");
        }
      });

      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: data.content,
          awaiting_confirmation: data.awaiting_confirmation,
          plan: data.plan,
          execution_results: data.execution_results,
          generated_files: data.generated_files,
          activityLog: turnActivity,
          timestamp: Date.now(),
        },
      ]);
    } catch (e: unknown) {
      // A thrown TypeError here (not one we raised above) means the request never
      // reached a server at all — an actual network failure, not an app error.
      const isNetworkFailure = e instanceof TypeError;
      const displayMessage = isNetworkFailure
        ? "We couldn't reach Nimbus. Check your connection and try again."
        : e instanceof Error
        ? e.message
        : "Something went wrong. Please try again.";

      addActivity("system", `Error: ${displayMessage}`, "error");
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: displayMessage,
          activityLog: turnActivity,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setLoading(false);
      setLiveActivity([]);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  return (
    <AWSGate>
    <div className="flex h-screen flex-col">
      <Navbar />

      <div className="mt-14 flex flex-1 overflow-hidden">
        {/* Session list is desktop furniture — on small screens the chat gets
            the full width (history stays reachable after resize/rotate).
            The wrapper reserves the sidebar's full width in BOTH states so
            toggling never reflows the centered chat column (the messages are
            width-capped anyway, so collapsing bought no usable space — only a
            distracting layout jump). */}
        <div className="hidden h-full w-64 shrink-0 md:block">
          <SessionSidebar
            currentSessionId={sessionId}
            onSelectSession={loadSession}
            onNewChat={startNewChat}
            collapsed={sidebarCollapsed}
            onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
          />
        </div>

        {/* ── Chat panel ── */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
            <div className="mx-auto max-w-3xl space-y-6">
              {messages.map((msg, i) => (
                <MessageBubble
                  key={i}
                  msg={msg}
                  onConfirm={() => sendMessage("yes", true)}
                  onDecline={() => sendMessage("no", false)}
                  isLatest={i === messages.length - 1}
                  loading={loading}
                  delay={i < loadedBatchSize ? Math.min(i, 15) * 0.03 : 0}
                />
              ))}

              {loading && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3">
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-ion-500 to-ion-400 text-[10px] font-bold text-white">
                    N
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 pt-1.5">
                      <span className="flex gap-1.5">
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ion-400 [animation-delay:0ms]" />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ion-400 [animation-delay:150ms]" />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ion-400 [animation-delay:300ms]" />
                      </span>
                      {/* Live pipeline stage — a real progress event from the backend,
                          not a canned "thinking" line. */}
                      {liveActivity.length > 0 && (
                        <motion.span
                          key={liveActivity[liveActivity.length - 1].message}
                          initial={{ opacity: 0, transform: "translateY(3px)" }}
                          animate={{ opacity: 1, transform: "translateY(0px)" }}
                          transition={{ duration: 0.2 }}
                          className="truncate text-xs text-slate-500"
                        >
                          {liveActivity[liveActivity.length - 1].message}
                        </motion.span>
                      )}
                    </div>
                    {liveActivity.length > 1 && (
                      <div className="mt-2 space-y-1 font-mono text-xs text-slate-600">
                        {liveActivity.slice(0, -1).map((entry, i) => (
                          <div key={i} className="flex gap-2">
                            <span className="text-emerald-500">✓</span>
                            <span>{entry.message}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          {/* Composer */}
          <div className="px-4 pb-6 sm:px-6">
            {/* Clickable starters — only on a fresh conversation */}
            {messages.length <= 1 && !loading && (
              <div className="mx-auto mb-3 flex max-w-3xl flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    className="rounded-full border border-slate-700 bg-slate-800/40 px-4 py-2 text-xs text-slate-300 transition hover:border-ion-500/40 hover:text-white active:scale-[0.97]"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendMessage(input);
              }}
              className="mx-auto max-w-3xl rounded-2xl border border-slate-700 bg-slate-800/50 p-2 transition focus-within:border-ion-500/50"
            >
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  const el = e.target;
                  el.style.height = "auto";
                  el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage(input);
                  }
                }}
                disabled={loading}
                rows={1}
                placeholder="Describe what you want to build on AWS..."
                className="max-h-40 w-full resize-none overflow-y-auto bg-transparent px-2 py-1.5 text-sm text-white placeholder-slate-500 outline-none transition-[height] duration-100 disabled:opacity-50"
              />
              <div className="flex items-center justify-between px-1 pt-1">
                <ModelSelector value={provider} onChange={changeProvider} />
                <button
                  type="submit"
                  disabled={loading || !input.trim()}
                  className="btn-ion flex h-8 w-8 items-center justify-center rounded-lg text-white disabled:opacity-30"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5l15-7.5-15-7.5v6l10 1.5-10 1.5v6z" />
                  </svg>
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
    </AWSGate>
  );
}
