"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Navbar from "../components/Navbar";
import AWSGate from "../components/AWSGate";

const API = "http://localhost:8000/api";

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
}

interface Alert {
  id: string;
  timestamp: string;
  message: string;
  severity: string;
}

interface BodyguardStatus {
  running: boolean;
  last_check: string | null;
  instances_stopped_total: number;
  recent_logs: LogEntry[];
  unread_alerts: Alert[];
}

interface TerminalLine {
  id: number;
  timestamp: string;
  source: "system" | "architect" | "executor" | "bodyguard";
  level: "info" | "success" | "warning" | "error";
  text: string;
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "00:00:00";
  }
}

function sourceColor(source: string) {
  switch (source) {
    case "architect": return "text-sky-400";
    case "executor": return "text-violet-400";
    case "bodyguard": return "text-emerald-400";
    default: return "text-slate-500";
  }
}

function levelPrefix(level: string) {
  switch (level) {
    case "success": return { char: "✓", color: "text-emerald-400" };
    case "warning": return { char: "!", color: "text-amber-400" };
    case "error": return { char: "✗", color: "text-red-400" };
    default: return { char: "›", color: "text-slate-600" };
  }
}

export default function TerminalPage() {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lineIdRef = useRef(0);
  const seenLogsRef = useRef(new Set<string>());

  const addLine = (
    source: TerminalLine["source"],
    level: TerminalLine["level"],
    text: string,
    timestamp?: string
  ) => {
    const key = `${timestamp}-${text}`;
    if (seenLogsRef.current.has(key)) return;
    seenLogsRef.current.add(key);

    setLines((prev) => {
      const next = [
        ...prev,
        {
          id: lineIdRef.current++,
          timestamp: timestamp || new Date().toISOString(),
          source,
          level,
          text,
        },
      ];
      return next.length > 500 ? next.slice(-300) : next;
    });
  };

  useEffect(() => {
    addLine("system", "info", "Nimbus Terminal v1.0 — Connecting to backend...");

    const poll = async () => {
      try {
        const res = await fetch(`${API}/dashboard/bodyguard`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: BodyguardStatus = await res.json();

        if (!connected) {
          setConnected(true);
          addLine("system", "success", "Connected to Nimbus backend");
          addLine("system", "info", `Bodyguard agent: ${data.running ? "ACTIVE" : "INACTIVE"}`);
          if (data.last_check) {
            addLine("system", "info", `Last patrol: ${formatTime(data.last_check)}`);
          }
          addLine("system", "info", `Total instances auto-stopped: ${data.instances_stopped_total}`);
          addLine("system", "info", "—".repeat(50));
          addLine("system", "info", "Streaming agent activity...");
        }

        if (!paused) {
          data.recent_logs.forEach((log) => {
            const level =
              log.level === "error" ? "error" :
              log.level === "warning" ? "warning" :
              log.message.toLowerCase().includes("stopped") ? "success" :
              "info";
            addLine("bodyguard", level as TerminalLine["level"], log.message, log.timestamp);
          });

          data.unread_alerts.forEach((alert) => {
            const level = alert.severity === "warning" ? "warning" : "info";
            addLine("bodyguard", level as TerminalLine["level"], `[ALERT] ${alert.message}`, alert.timestamp);
          });
        }
      } catch {
        if (connected) {
          addLine("system", "error", "Lost connection to backend");
          setConnected(false);
        }
      }
    };

    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [connected, paused]);

  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [lines, paused]);

  return (
    <AWSGate>
      <div className="flex h-screen flex-col bg-grid">
        <Navbar />

        <div className="flex flex-1 flex-col overflow-hidden pt-14">
          <div className="flex items-center justify-between border-b border-slate-800 bg-slate-950/80 px-6 py-3">
            <div className="flex items-center gap-3">
              <div className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
              <span className="font-mono text-xs text-slate-400">
                nimbus-terminal
              </span>
              <span className="font-mono text-xs text-slate-600">
                {connected ? "connected" : "disconnected"}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setPaused(!paused)}
                className={`rounded-md border px-3 py-1 font-mono text-xs transition ${
                  paused
                    ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                    : "border-slate-700 bg-slate-800/50 text-slate-400 hover:text-white"
                }`}
              >
                {paused ? "PAUSED" : "LIVE"}
              </button>
              <button
                onClick={() => {
                  setLines([]);
                  seenLogsRef.current.clear();
                  addLine("system", "info", "Terminal cleared");
                }}
                className="rounded-md border border-slate-700 bg-slate-800/50 px-3 py-1 font-mono text-xs text-slate-400 transition hover:text-white"
              >
                CLEAR
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto bg-slate-950 p-4 font-mono text-xs leading-relaxed">
            <AnimatePresence>
              {lines.map((line) => {
                const prefix = levelPrefix(line.level);
                return (
                  <motion.div
                    key={line.id}
                    initial={{ opacity: 0, x: -4 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.15 }}
                    className="flex gap-2 py-0.5"
                  >
                    <span className="shrink-0 text-slate-700 select-none">
                      {formatTime(line.timestamp)}
                    </span>
                    <span className={`shrink-0 ${prefix.color} select-none`}>
                      {prefix.char}
                    </span>
                    <span className={`shrink-0 ${sourceColor(line.source)} select-none`}>
                      [{line.source.padEnd(9)}]
                    </span>
                    <span
                      className={
                        line.level === "error"
                          ? "text-red-300"
                          : line.level === "warning"
                          ? "text-amber-300"
                          : line.level === "success"
                          ? "text-emerald-300"
                          : "text-slate-300"
                      }
                    >
                      {line.text}
                    </span>
                  </motion.div>
                );
              })}
            </AnimatePresence>

            {connected && !paused && (
              <div className="flex items-center gap-2 py-0.5 text-slate-600">
                <span className="animate-pulse">_</span>
                <span>awaiting next event...</span>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>
      </div>
    </AWSGate>
  );
}
