"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Navbar from "../components/Navbar";
import AWSGate from "../components/AWSGate";

const API = "http://localhost:8000/api";

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

interface TerminalLine {
  id: number;
  timestamp: string;
  source: "system" | "user" | "git" | "aws";
  text: string;
  type: "input" | "output" | "error" | "info";
}

interface BodyguardStatus {
  running: boolean;
  last_check: string | null;
  instances_stopped_total: number;
  recent_logs: { timestamp: string; level: string; message: string }[];
  unread_alerts: { id: string; timestamp: string; message: string; severity: string }[];
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

// ── Editor Panel ─────────────────────────────────────────────────────────

interface WorkspaceFile {
  name: string;
  size: number;
}

function EditorPanel({ onFileChange }: { onFileChange?: () => void }) {
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const loadFiles = useCallback(async () => {
    try {
      const res = await fetch(`${API}/workspace/files`);
      const data = await res.json();
      setFiles(data.files || []);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadFiles();
    const id = setInterval(loadFiles, 4000);
    return () => clearInterval(id);
  }, [loadFiles]);

  const openFile = async (name: string) => {
    if (dirty && activeFile) {
      await saveFile();
    }
    try {
      const res = await fetch(`${API}/workspace/file/${encodeURIComponent(name)}`);
      const data = await res.json();
      if (data.success) {
        setActiveFile(name);
        setContent(data.content);
        setDirty(false);
      }
    } catch {
      // ignore
    }
  };

  const saveFile = async () => {
    if (!activeFile) return;
    setSaving(true);
    try {
      await fetch(`${API}/workspace/file/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: activeFile, content }),
      });
      setDirty(false);
      onFileChange?.();
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  const fileIcon = (name: string) => {
    if (name.endsWith(".json")) return "{ }";
    if (name.endsWith(".sh")) return "#!/";
    if (name.endsWith(".yml") || name.endsWith(".yaml")) return "---";
    if (name.endsWith(".py")) return "py";
    if (name.endsWith(".md")) return "md";
    if (name.endsWith(".ts") || name.endsWith(".tsx")) return "ts";
    if (name.endsWith(".js") || name.endsWith(".jsx")) return "js";
    return "txt";
  };

  return (
    <div className="flex h-full flex-col border-t border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-2">
          <svg className="h-3.5 w-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10" />
          </svg>
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Editor
          </span>
          {activeFile && (
            <span className="ml-1 font-mono text-[10px] text-slate-500">
              {activeFile}{dirty ? " *" : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {dirty && (
            <button
              onClick={saveFile}
              disabled={saving}
              className="rounded bg-sky-500/20 px-2 py-0.5 text-[10px] font-medium text-sky-400 transition hover:bg-sky-500/30 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded p-1 text-slate-500 transition hover:bg-slate-800 hover:text-white"
          >
            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {sidebarOpen && (
          <div className="w-36 shrink-0 overflow-y-auto border-r border-slate-800 bg-slate-950/80 py-1">
            {files.length === 0 ? (
              <p className="px-3 py-2 text-[10px] text-slate-600">No files yet</p>
            ) : (
              files.map((f) => (
                <button
                  key={f.name}
                  onClick={() => openFile(f.name)}
                  className={`flex w-full items-center gap-1.5 px-3 py-1 text-left text-[10px] transition ${
                    activeFile === f.name
                      ? "bg-sky-500/10 text-sky-300"
                      : "text-slate-400 hover:bg-slate-800/50 hover:text-white"
                  }`}
                >
                  <span className="shrink-0 font-mono text-[8px] font-bold text-slate-600">
                    {fileIcon(f.name)}
                  </span>
                  <span className="truncate">{f.name}</span>
                </button>
              ))
            )}
          </div>
        )}

        <div className="flex-1 overflow-hidden">
          {activeFile ? (
            <textarea
              value={content}
              onChange={(e) => {
                setContent(e.target.value);
                setDirty(true);
              }}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "s") {
                  e.preventDefault();
                  saveFile();
                }
              }}
              spellCheck={false}
              className="h-full w-full resize-none bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-200 outline-none"
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <svg className="mb-2 h-5 w-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
              </svg>
              <p className="text-[10px] text-slate-600">Select a file to edit</p>
              <p className="mt-0.5 text-[10px] text-slate-700">Deploy to generate files</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Terminal Panel ────────────────────────────────────────────────────────

function TerminalPanel({ activity }: { activity: ActivityEntry[] }) {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [input, setInput] = useState("");
  const [cwd, setCwd] = useState("~");
  const [githubLinked, setGithubLinked] = useState(false);
  const [linkPrompt, setLinkPrompt] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const lineIdRef = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const seenLogsRef = useRef(new Set<string>());

  const addLine = useCallback((source: TerminalLine["source"], text: string, type: TerminalLine["type"] = "output") => {
    setLines((prev) => {
      const next = [
        ...prev,
        { id: lineIdRef.current++, timestamp: new Date().toISOString(), source, text, type },
      ];
      return next.length > 300 ? next.slice(-200) : next;
    });
  }, []);

  useEffect(() => {
    addLine("system", "Nimbus Terminal v1.0", "info");
    addLine("system", "Type 'help' for commands", "info");

    fetch(`${API}/workspace/github/status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.linked) {
          setGithubLinked(true);
          addLine("git", `Connected to ${data.repo_url}`, "info");
        }
      })
      .catch(() => {});
  }, [addLine]);

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch(`${API}/dashboard/bodyguard`);
        if (!res.ok) return;
        const data: BodyguardStatus = await res.json();
        data.recent_logs.forEach((log) => {
          const key = `${log.timestamp}-${log.message}`;
          if (!seenLogsRef.current.has(key)) {
            seenLogsRef.current.add(key);
            addLine("aws", `[bodyguard] ${log.message}`, log.level === "error" ? "error" : "output");
          }
        });
      } catch { /* ignore */ }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [addLine]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  const execBackend = async (command: string) => {
    try {
      const res = await fetch(`${API}/workspace/exec`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const data = await res.json();
      if (data.cwd) setCwd(data.cwd);
      if (data.output) {
        const source = command.startsWith("git") ? "git" as const : "system" as const;
        data.output.split("\n").forEach((line: string) => {
          addLine(source, line, data.success ? "output" : "error");
        });
      }
    } catch {
      addLine("system", "Could not reach backend", "error");
    }
  };

  const linkGitHub = async (url: string) => {
    addLine("git", `Linking: ${url}`, "info");
    try {
      const res = await fetch(`${API}/workspace/github/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: url }),
      });
      const data = await res.json();
      if (data.success) {
        setGithubLinked(true);
        addLine("git", data.message, "output");
        addLine("system", "Use git commands to manage your repo", "info");
      } else {
        addLine("git", `Failed: ${data.message}`, "error");
      }
    } catch {
      addLine("system", "Could not reach backend", "error");
    }
  };

  const handleCommand = async (cmd: string) => {
    const trimmed = cmd.trim();
    if (!trimmed) return;
    setInput("");
    addLine("user", `${cwd} $ ${trimmed}`, "input");

    const parts = trimmed.split(/\s+/);
    const command = parts[0].toLowerCase();

    if (command === "help") {
      addLine("system", "Commands: cd, ls, cat, mkdir, touch, rm, mv, cp, echo,", "info");
      addLine("system", "  grep, find, chmod, head, tail, wc, diff, tree, pwd", "info");
      addLine("system", "  git [any subcommand]  — full git support", "info");
      addLine("system", "  github link <url>     — link GitHub repo", "info");
      addLine("system", "  github status         — connection info", "info");
      addLine("system", "  files                 — list workspace files", "info");
      addLine("system", "  logs                  — recent agent activity", "info");
      addLine("system", "  clear                 — clear terminal", "info");
      return;
    }
    if (command === "clear") {
      setLines([]);
      lineIdRef.current = 0;
      seenLogsRef.current.clear();
      return;
    }
    if (command === "logs") {
      if (activity.length === 0) {
        addLine("system", "No agent activity yet", "info");
      } else {
        activity.slice(-10).forEach((e) => {
          addLine("system", `[${e.agent}] ${e.message}`, e.type === "error" ? "error" : "output");
        });
      }
      return;
    }
    if (command === "files") {
      try {
        const res = await fetch(`${API}/workspace/files`);
        const data = await res.json();
        if (!data.files.length) {
          addLine("system", "No files yet. Deploy from chat to generate.", "info");
        } else {
          data.files.forEach((f: { name: string; size: number }) => {
            addLine("system", `  ${f.name}  (${f.size}B)`, "output");
          });
        }
      } catch { addLine("system", "Could not reach backend", "error"); }
      return;
    }
    if (command === "github") {
      if (parts[1] === "link" && parts[2]) {
        await linkGitHub(parts[2]);
      } else if (parts[1] === "link") {
        setLinkPrompt(true);
        addLine("system", "Enter repo URL above", "info");
      } else if (parts[1] === "status") {
        try {
          const res = await fetch(`${API}/workspace/github/status`);
          const data = await res.json();
          addLine("git", data.linked ? `${data.repo_url} (${data.branch})` : "Not linked", "output");
        } catch { addLine("system", "Could not reach backend", "error"); }
      } else {
        addLine("system", "Usage: github link <url> | github status", "info");
      }
      return;
    }

    await execBackend(trimmed);
  };

  const lineColor = (type: TerminalLine["type"]) => {
    switch (type) {
      case "input": return "text-sky-300";
      case "error": return "text-red-400";
      case "info": return "text-slate-500";
      default: return "text-slate-300";
    }
  };

  const sourceTag = (source: TerminalLine["source"]) => {
    switch (source) {
      case "git": return <span className="text-amber-400">git</span>;
      case "aws": return <span className="text-violet-400">aws</span>;
      case "user": return null;
      default: return <span className="text-slate-600">sys</span>;
    }
  };

  return (
    <div className="flex h-full flex-col border-t border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-1.5">
        <div className="flex items-center gap-2">
          <svg className="h-3 w-3 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z" />
          </svg>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Terminal</span>
        </div>
        <button
          onClick={() => {
            if (!githubLinked) setLinkPrompt(true);
          }}
          className={`flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[9px] font-medium transition ${
            githubLinked
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              : "border-slate-700 bg-slate-800/50 text-slate-500 hover:text-white"
          }`}
        >
          <svg className="h-2.5 w-2.5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
          </svg>
          {githubLinked ? "Linked" : "GitHub"}
        </button>
      </div>

      {linkPrompt && !githubLinked && (
        <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900/80 px-3 py-1.5">
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (repoUrl.trim()) {
                setLinkPrompt(false);
                await linkGitHub(repoUrl.trim());
                setRepoUrl("");
              }
            }}
            className="flex flex-1 items-center gap-1.5"
          >
            <input
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/user/repo.git"
              className="flex-1 rounded bg-slate-800 px-2 py-0.5 font-mono text-[10px] text-white placeholder-slate-600 outline-none focus:ring-1 focus:ring-amber-500/30"
              autoFocus
            />
            <button type="submit" className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-medium text-amber-400 hover:bg-amber-500/30">Link</button>
            <button type="button" onClick={() => { setLinkPrompt(false); setRepoUrl(""); }} className="text-[9px] text-slate-500 hover:text-white">Cancel</button>
          </form>
        </div>
      )}

      <div className="flex-1 overflow-y-auto bg-slate-950 px-3 py-2 font-mono text-[11px] leading-relaxed">
        {lines.map((line) => (
          <div key={line.id} className={`flex gap-1.5 py-px ${lineColor(line.type)}`}>
            {line.type !== "input" && sourceTag(line.source) && (
              <span className="shrink-0 select-none">[{sourceTag(line.source)}]</span>
            )}
            <span className="whitespace-pre-wrap">{line.text}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); handleCommand(input); }}
        className="flex items-center border-t border-slate-800 bg-slate-950 px-3 py-1.5"
      >
        <span className="mr-1.5 font-mono text-[10px] text-emerald-400 select-none">{cwd} $</span>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="command..."
          className="flex-1 bg-transparent font-mono text-[11px] text-white placeholder-slate-600 outline-none"
        />
      </form>
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
              className="rounded-lg border border-slate-600 px-4 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="rounded-lg bg-gradient-to-r from-sky-500 to-cyan-400 px-4 py-1.5 text-xs font-semibold text-white shadow-md shadow-sky-500/20 transition hover:brightness-110"
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
          className="flex items-center gap-1 rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-1 text-xs font-medium text-violet-300 transition hover:bg-violet-500/20"
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
            className="flex w-full items-center gap-3 rounded-lg bg-slate-800/50 p-2.5 text-left transition hover:bg-slate-800/80"
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
}: {
  msg: Message;
  onConfirm: () => void;
  onDecline: () => void;
  isLatest: boolean;
  loading: boolean;
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

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-gradient-to-r from-sky-600 to-sky-500 text-white rounded-br-sm"
            : "glass text-slate-200 rounded-bl-sm"
        }`}
      >
        {!isUser && (
          <p className="mb-1 text-xs font-semibold text-sky-400 tracking-wide">NIMBUS</p>
        )}

        {/* Show plan card if available, otherwise text */}
        {msg.plan && msg.awaiting_confirmation ? (
          <PlanCard
            plan={msg.plan}
            onConfirm={onConfirm}
            onDecline={onDecline}
            disabled={!isLatest || loading}
          />
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
      </div>
    </motion.div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hey! I'm Nimbus. Tell me what you want to build on AWS and I'll design the architecture for you.\n\nYou can say things like:\n**\"I need a REST API with a database\"**\n**\"Set up a static website with storage\"**\n**\"Create a serverless function that runs every hour\"**",
      timestamp: Date.now(),
    },
  ]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [freeTierMode, setFreeTierMode] = useState(true);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const stored = localStorage.getItem("nimbus_free_tier");
    if (stored !== null) setFreeTierMode(JSON.parse(stored));
  }, []);

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

    // Activity log
    if (confirm === true) {
      addActivity("system", "User approved deployment plan", "info");
      addActivity("executor", "Initializing resource provisioning...", "thinking");
    } else if (confirm === false) {
      addActivity("system", "User cancelled the plan", "info");
    } else {
      addActivity("system", `User request: "${text}"`, "info");
      addActivity("architect", "Analyzing request with Amazon Nova AI...", "thinking");
    }

    try {
      const body: Record<string, unknown> = { message: text, session_id: sessionId, free_tier_mode: freeTierMode };
      if (confirm !== undefined) body.confirm = confirm;

      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

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
      const errMsg = e instanceof Error ? e.message : "Cannot reach backend";
      addActivity("system", `Error: ${errMsg}`, "error");
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `Error: ${errMsg}. Is the backend running?`,
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

      <div className="flex flex-1 overflow-hidden pt-14">
        {/* ── Chat panel ── */}
        <div className="flex flex-1 flex-col border-r border-slate-800">
          {/* Messages */}
          <div className="flex-1 space-y-4 overflow-y-auto px-6 py-6">
            {messages.map((msg, i) => (
              <MessageBubble
                key={i}
                msg={msg}
                onConfirm={() => sendMessage("yes", true)}
                onDecline={() => sendMessage("no", false)}
                isLatest={i === messages.length - 1}
                loading={loading}
              />
            ))}

            {loading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex justify-start"
              >
                <div className="glass rounded-2xl rounded-bl-sm px-4 py-3">
                  <p className="mb-1 text-xs font-semibold text-sky-400">NIMBUS</p>
                  <div className="flex gap-1.5">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:0ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:150ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:300ms]" />
                  </div>
                </div>
              </motion.div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-slate-800 bg-slate-950/50 px-6 py-4">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendMessage(input);
              }}
              className="flex gap-3"
            >
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={loading}
                placeholder="Describe what you want to build on AWS..."
                className="flex-1 rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none transition focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30 disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                className="rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-sky-500/20 transition hover:brightness-110 disabled:opacity-40"
              >
                Send
              </button>
            </form>
          </div>
        </div>

        {/* ── Right panel: Activity + Editor + Terminal ── */}
        <div className="hidden w-[480px] flex-col bg-slate-950/50 lg:flex">
          <div className="flex h-[25%] flex-col overflow-hidden">
            <ActivityPanel entries={activity} />
          </div>
          <div className="flex h-[40%] flex-col overflow-hidden">
            <EditorPanel />
          </div>
          <div className="flex h-[35%] flex-col overflow-hidden">
            <TerminalPanel activity={activity} />
          </div>
        </div>
      </div>
    </div>
    </AWSGate>
  );
}
