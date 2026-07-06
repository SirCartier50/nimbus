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

interface ActivityEntry {
  timestamp: number;
  agent: "architect" | "executor" | "bodyguard" | "system";
  message: string;
  type: "info" | "success" | "error" | "thinking";
}

// ── Activity Panel ────────────────────────────────────────────────────────

function ActivityPanel({ entries }: { entries: ActivityEntry[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  const agentColor = (agent: string) => {
    switch (agent) {
      case "architect": return "text-sky-400";
      case "executor": return "text-violet-400";
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
      case "thinking": return "text-sky-400 animate-pulse";
      default: return "text-slate-500";
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
        <div className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Agent Activity
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs">
        {entries.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <svg className="mb-2 h-6 w-6 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" /></svg>
            <p className="text-slate-600">Agent activity will appear here</p>
            <p className="mt-1 text-slate-700">Send a message to start</p>
          </div>
        ) : (
          <div className="space-y-1.5">
            <AnimatePresence>
              {entries.map((entry, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2 }}
                  className="flex gap-2 leading-relaxed"
                >
                  <span className={`shrink-0 ${typeColor(entry.type)}`}>
                    {typeIcon(entry.type)}
                  </span>
                  <span className={`shrink-0 ${agentColor(entry.agent)}`}>
                    [{entry.agent}]
                  </span>
                  <span className={entry.type === "error" ? "text-red-300" : "text-slate-300"}>
                    {entry.message}
                  </span>
                </motion.div>
              ))}
            </AnimatePresence>
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Resource Map ──────────────────────────────────────────────────────────

interface ResourceItem {
  id?: string;
  name?: string;
  state?: string;
  error?: string;
  [key: string]: unknown;
}

interface DashboardData {
  ec2: ResourceItem[];
  s3: ResourceItem[];
  dynamodb: ResourceItem[];
  lambda: ResourceItem[];
  bodyguard: { running: boolean; instances_stopped_total: number; unread_alerts: unknown[] };
}

const RESOURCE_GROUPS: { key: "ec2" | "s3" | "dynamodb" | "lambda"; label: string; icon: string }[] = [
  { key: "ec2", label: "EC2", icon: "▣" },
  { key: "s3", label: "S3", icon: "◫" },
  { key: "dynamodb", label: "DynamoDB", icon: "▤" },
  { key: "lambda", label: "Lambda", icon: "ƒ" },
];

function ResourceMap() {
  const authFetch = useAuthFetch();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/dashboard`);
      if (res.ok) setData(await res.json());
    } catch {
      // keep showing the last good snapshot rather than clearing it
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, [load]);

  const stateColor = (state?: string) => {
    switch (state) {
      case "running":
      case "active":
        return "bg-emerald-400";
      case "stopped":
      case "stopping":
        return "bg-amber-400";
      default:
        return "bg-slate-500";
    }
  };

  const detailLine = (key: string, r: ResourceItem) => {
    if (key === "ec2") return `${r.type ?? ""} · ${r.state}${r.public_ip ? ` · ${r.public_ip}` : ""}`;
    if (key === "s3") return `${r.state ?? "active"}`;
    if (key === "dynamodb") return `${(r.item_count as number) ?? 0} items · ${r.state}`;
    if (key === "lambda") return `${r.runtime ?? ""} · ${r.memory ?? ""}MB`;
    return "";
  };

  const groupsWithItems = RESOURCE_GROUPS.map((g) => ({
    ...g,
    items: (data?.[g.key] ?? []).filter((r) => !r.error),
  }));
  const totalResources = groupsWithItems.reduce((sum, g) => sum + g.items.length, 0);

  return (
    <div className="flex h-full flex-col border-t border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <svg className="h-3.5 w-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25Z" />
          </svg>
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Resource Map</span>
        </div>
        {data?.bodyguard && (
          <span
            className={`flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[9px] font-medium ${
              data.bodyguard.running
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : "border-slate-700 bg-slate-800/50 text-slate-500"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${data.bodyguard.running ? "animate-pulse bg-emerald-400" : "bg-slate-600"}`} />
            Bodyguard
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {loading && !data ? (
          <div className="flex h-full items-center justify-center text-xs text-slate-600">Loading resources...</div>
        ) : totalResources === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <svg className="mb-2 h-6 w-6 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 7.5l-9-5.25L3 7.5m18 0-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />
            </svg>
            <p className="text-xs text-slate-600">No resources yet</p>
            <p className="mt-1 text-[10px] text-slate-700">Deploy something from chat to see it here</p>
          </div>
        ) : (
          <div className="space-y-4">
            {groupsWithItems.map((g) =>
              g.items.length === 0 ? null : (
                <div key={g.key}>
                  <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    {g.icon} {g.label} <span className="text-slate-600">({g.items.length})</span>
                  </p>
                  <div className="space-y-1.5">
                    {g.items.map((r) => (
                      <div key={String(r.id ?? r.name)} className="rounded-lg bg-slate-800/50 p-2.5">
                        <div className="flex items-center gap-2">
                          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${stateColor(r.state)}`} />
                          <span className="truncate text-xs font-medium text-white">{r.name ?? r.id}</span>
                        </div>
                        <p className="mt-1 truncate pl-3.5 text-[10px] text-slate-500">{detailLine(g.key, r)}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )
            )}
          </div>
        )}
      </div>
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
    <div className="mt-3 rounded-xl border border-sky-500/20 bg-sky-500/5 p-4">
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

      <div className="mt-3 flex items-center justify-between">
        <p className="text-xs text-slate-500">
          Est. cost: <span className="text-slate-300">{plan.estimated_monthly_cost}</span>
          {plan.cost_warning && (
            <span className="ml-2 text-amber-400">{plan.cost_warning}</span>
          )}
        </p>

        {!disabled && (
          <div className="flex gap-2">
            <button
              onClick={onDecline}
              className="rounded-lg border border-slate-600 px-4 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700 active:scale-[0.97]"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="rounded-lg bg-gradient-to-r from-sky-500 to-cyan-400 px-4 py-1.5 text-xs font-semibold text-white shadow-md shadow-sky-500/20 transition hover:brightness-110 active:scale-[0.97]"
            >
              Deploy
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
    <div className="mt-3 rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="h-4 w-4 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
          <span className="text-xs font-semibold text-violet-300">Generated Files</span>
        </div>
        <button
          onClick={downloadAll}
          className="flex items-center gap-1 rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-1 text-xs font-medium text-violet-300 transition hover:bg-violet-500/20 active:scale-[0.97]"
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
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-slate-700/50 font-mono text-[9px] font-bold text-violet-300">
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
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-cyan-400 text-[10px] font-bold text-white">
        N
      </div>
      <div className="min-w-0 flex-1 text-sm leading-relaxed text-slate-200">{body}</div>
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
}: {
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
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

  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-r border-slate-800 bg-slate-950/50">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="flex w-full items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white active:scale-[0.98]"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New chat
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
                  s.id === currentSessionId ? "bg-sky-500/10" : "hover:bg-slate-800/60"
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
                    className="w-full rounded bg-slate-800 px-1.5 py-0.5 text-xs text-white outline-none ring-1 ring-sky-500/40"
                  />
                ) : (
                  <>
                    <button
                      onClick={() => onSelectSession(s.id)}
                      title={s.title}
                      className={`min-w-0 flex-1 truncate text-left text-xs active:scale-[0.98] ${
                        s.id === currentSessionId ? "text-sky-300" : "text-slate-400 group-hover:text-white"
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

const PROVIDERS = [
  { value: "bedrock", label: "Bedrock · Nova" },
  { value: "groq", label: "Groq · Llama 3.3" },
  { value: "openrouter", label: "OpenRouter · Llama 3.3" },
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
        <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
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
                    p.value === value ? "bg-sky-500/10 text-sky-300" : "text-slate-300 hover:bg-slate-800"
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
    "Hey! I'm Nimbus AI. Tell me what you want to build on AWS and I'll design the architecture for you.\n\nYou can say things like:\n**\"I need a REST API with a database\"**\n**\"Set up a static website with storage\"**\n**\"Create a serverless function that runs every hour\"**",
  timestamp: Date.now(),
};

export default function ChatPage() {
  const authFetch = useAuthFetch();
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [freeTierMode, setFreeTierMode] = useState(true);
  const [provider, setProvider] = useState("bedrock");
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
    if (storedProvider) setProvider(storedProvider);

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
    setActivity([]);
    setLoadedBatchSize(0);
  };

  const loadSession = async (id: string) => {
    if (id === sessionId) return;
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
      setActivity([]);
    } catch {
      // ignore — keep the current conversation on screen
    }
  };

  const addActivity = (agent: ActivityEntry["agent"], message: string, type: ActivityEntry["type"] = "info") => {
    setActivity((prev) => [...prev, { timestamp: Date.now(), agent, message, type }]);
  };

  const sendMessage = async (text: string, confirm?: boolean) => {
    if (!text.trim() && confirm === undefined) return;
    setLoading(true);

    // Add user message
    const userContent = confirm === true ? "Yes, deploy" : confirm === false ? "No, cancel" : text;
    setMessages((m) => [...m, { role: "user", content: userContent, timestamp: Date.now() }]);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";

    // Activity log
    if (confirm === true) {
      addActivity("system", "User approved deployment plan", "info");
      addActivity("executor", "Initializing resource provisioning...", "thinking");
    } else if (confirm === false) {
      addActivity("system", "User cancelled the plan", "info");
    } else {
      addActivity("system", `User request: "${text}"`, "info");
      const providerLabel = PROVIDERS.find((p) => p.value === provider)?.label ?? provider;
      addActivity("architect", `Analyzing request with ${providerLabel}...`, "thinking");
    }

    try {
      const body: Record<string, unknown> = {
        message: text,
        session_id: sessionId,
        free_tier_mode: freeTierMode,
        provider,
      };
      if (confirm !== undefined) body.confirm = confirm;

      const res = await authFetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        // 4xx bodies carry a specific, user-actionable reason (e.g. bad input);
        // 5xx bodies may carry internal detail we shouldn't show verbatim.
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

      const data = await res.json();
      if (!sessionId) setSessionId(data.session_id);

      // Update activity based on response
      if (data.awaiting_confirmation) {
        addActivity("architect", "Infrastructure plan generated", "success");
        const steps = data.plan?.plan ?? [];
        steps.forEach((s: PlanStep) => {
          addActivity("architect", `Step ${s.step}: ${s.description}`, "info");
        });
        addActivity("system", "Waiting for user approval...", "info");
      } else if (data.execution_results) {
        data.execution_results.forEach((r: ExecResult) => {
          if (r.success) {
            addActivity("executor", `${r.message}`, "success");
          } else {
            addActivity("executor", `Failed: ${r.description} — ${r.error}`, "error");
          }
        });
        addActivity("bodyguard", "Resources detected, monitoring initiated", "info");
        if (data.generated_files) {
          const fileCount = Object.keys(data.generated_files).length;
          addActivity("system", `${fileCount} deployment config file(s) generated`, "success");
        }
      } else if (confirm === false) {
        addActivity("architect", "Plan discarded", "info");
      }

      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: data.content,
          awaiting_confirmation: data.awaiting_confirmation,
          plan: data.plan,
          execution_results: data.execution_results,
          generated_files: data.generated_files,
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
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  return (
    <AWSGate>
    <div className="flex h-screen flex-col bg-grid">
      <Navbar />

      <div className="mt-14 flex flex-1 overflow-hidden">
        <SessionSidebar currentSessionId={sessionId} onSelectSession={loadSession} onNewChat={startNewChat} />

        {/* ── Chat panel ── */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 py-6">
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
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-cyan-400 text-[10px] font-bold text-white">
                    N
                  </div>
                  <div className="flex items-center gap-1.5 pt-1.5">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:0ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:150ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:300ms]" />
                  </div>
                </motion.div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          {/* Composer */}
          <div className="border-t border-slate-800 bg-slate-950/50 px-6 py-4">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendMessage(input);
              }}
              className="mx-auto max-w-3xl rounded-2xl border border-slate-700 bg-slate-800/50 p-2 transition focus-within:border-sky-500/50"
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
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-r from-sky-500 to-cyan-400 text-white shadow-md shadow-sky-500/20 transition hover:brightness-110 active:scale-[0.93] disabled:active:scale-100 disabled:opacity-30"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5l15-7.5-15-7.5v6l10 1.5-10 1.5v6z" />
                  </svg>
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* ── Right panel: Activity + Resource Map ── */}
        <div className="hidden w-[420px] shrink-0 flex-col border-l border-slate-800 bg-slate-950/50 lg:flex">
          <div className="flex h-[40%] flex-col overflow-hidden">
            <ActivityPanel entries={activity} />
          </div>
          <div className="flex h-[60%] flex-col overflow-hidden">
            <ResourceMap />
          </div>
        </div>
      </div>
    </div>
    </AWSGate>
  );
}
