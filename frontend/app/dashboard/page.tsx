"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import Navbar from "../components/Navbar";
import AWSGate from "../components/AWSGate";

const API = "http://localhost:8000/api";

// ── Types ─────────────────────────────────────────────────────────────────

interface Resource {
  id: string;
  name: string;
  state: string;
  resource_type: string;
  type?: string;
  public_ip?: string;
  launch_time?: string;
  created?: string;
  item_count?: number;
  runtime?: string;
  memory?: number;
  last_modified?: string;
  size_bytes?: number;
  error?: string;
}

interface BodyguardStatus {
  running: boolean;
  last_check: string | null;
  instances_stopped_total: number;
  unread_alerts: Alert[];
  recent_logs: LogEntry[];
}

interface Alert {
  id: string;
  timestamp: string;
  message: string;
  severity: string;
  read: boolean;
}

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
}

interface DashboardData {
  ec2: Resource[];
  s3: Resource[];
  dynamodb: Resource[];
  lambda: Resource[];
  bodyguard: BodyguardStatus;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function stateColor(state: string) {
  switch (state) {
    case "running":
    case "active":
      return "bg-emerald-500/15 text-emerald-400 border-emerald-500/25";
    case "stopped":
    case "stopping":
      return "bg-amber-500/15 text-amber-400 border-amber-500/25";
    case "pending":
      return "bg-sky-500/15 text-sky-400 border-sky-500/25";
    default:
      return "bg-slate-500/15 text-slate-400 border-slate-500/25";
  }
}

function ResourceIcon({ type }: { type: string }) {
  const icons: Record<string, React.ReactNode> = {
    ec2: <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg>,
    s3: <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" /><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" /></svg>,
    dynamodb: <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path d="M4 7v10c0 2.21 3.58 4 8 4s8-1.79 8-4V7" /><ellipse cx="12" cy="7" rx="8" ry="4" /><path d="M4 12c0 2.21 3.58 4 8 4s8-1.79 8-4" /></svg>,
    lambda: <span className="text-sm font-bold font-mono">fn</span>,
  };
  return icons[type] ?? <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z" /></svg>;
}

function resourceLabel(type: string) {
  return { ec2: "EC2 Instance", s3: "S3 Bucket", dynamodb: "DynamoDB Table", lambda: "Lambda Function" }[type] ?? type;
}

// ── Animation ─────────────────────────────────────────────────────────────

const fadeIn = {
  hidden: { opacity: 0, y: 12 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.08, duration: 0.4, ease: "easeOut" as const },
  }),
};

// ── Components ────────────────────────────────────────────────────────────

function StatCard({ label, value, icon, color }: { label: string; value: string | number; icon: React.ReactNode; color: string }) {
  return (
    <div className="glass rounded-xl p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</p>
          <p className={`mt-1 text-2xl font-bold ${color}`}>{value}</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-800/80 text-slate-400">
          {icon}
        </div>
      </div>
    </div>
  );
}

function ResourceCard({ resource }: { resource: Resource }) {
  if (resource.error) {
    return (
      <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
        {resource.error}
      </div>
    );
  }

  return (
    <div className="glass group rounded-xl p-5 transition-all duration-200 hover:border-sky-500/30 glow-blue-hover">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-800 text-slate-400">
            <ResourceIcon type={resource.resource_type} />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">{resource.name}</p>
            <p className="text-xs text-slate-500">{resourceLabel(resource.resource_type)}</p>
          </div>
        </div>
        <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${stateColor(resource.state)}`}>
          {resource.state}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-slate-400">
        {resource.type && (
          <div>
            <span className="text-slate-600">Type</span>
            <p className="text-slate-300">{resource.type}</p>
          </div>
        )}
        {resource.public_ip && (
          <div>
            <span className="text-slate-600">IP</span>
            <p className="text-slate-300 font-mono">{resource.public_ip}</p>
          </div>
        )}
        {resource.runtime && (
          <div>
            <span className="text-slate-600">Runtime</span>
            <p className="text-slate-300">{resource.runtime}</p>
          </div>
        )}
        {resource.memory !== undefined && (
          <div>
            <span className="text-slate-600">Memory</span>
            <p className="text-slate-300">{resource.memory} MB</p>
          </div>
        )}
        {resource.item_count !== undefined && (
          <div>
            <span className="text-slate-600">Items</span>
            <p className="text-slate-300">{resource.item_count.toLocaleString()}</p>
          </div>
        )}
        {resource.size_bytes !== undefined && resource.size_bytes > 0 && (
          <div>
            <span className="text-slate-600">Size</span>
            <p className="text-slate-300">{(resource.size_bytes / 1024).toFixed(1)} KB</p>
          </div>
        )}
      </div>

      <div className="mt-3 border-t border-slate-800 pt-3">
        <p className="truncate text-xs text-slate-600 font-mono">{resource.id}</p>
      </div>
    </div>
  );
}

function BodyguardPanel({ bodyguard }: { bodyguard: BodyguardStatus }) {
  return (
    <div className="glass rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" /></svg>
            {bodyguard.running && (
              <span className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
            )}
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Bodyguard Agent</p>
            <p className="text-xs text-slate-500">
              {bodyguard.running ? "Actively patrolling" : "Inactive"}
            </p>
          </div>
        </div>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
            bodyguard.running
              ? "border-emerald-500/25 bg-emerald-500/15 text-emerald-400"
              : "border-slate-600 bg-slate-800 text-slate-400"
          }`}
        >
          {bodyguard.running ? "Active" : "Stopped"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4">
        <div className="text-center">
          <p className="text-lg font-bold text-white">{bodyguard.instances_stopped_total}</p>
          <p className="text-xs text-slate-500">Instances Stopped</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-white">{bodyguard.unread_alerts.length}</p>
          <p className="text-xs text-slate-500">Active Alerts</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-white">
            {bodyguard.last_check
              ? new Date(bodyguard.last_check).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
              : "—"}
          </p>
          <p className="text-xs text-slate-500">Last Check</p>
        </div>
      </div>

      {/* Alerts */}
      {bodyguard.unread_alerts.length > 0 && (
        <div className="mb-4 space-y-2">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Alerts</p>
          {bodyguard.unread_alerts.slice(0, 3).map((alert) => (
            <div
              key={alert.id}
              className={`rounded-lg p-3 text-xs ${
                alert.severity === "warning"
                  ? "border border-amber-500/20 bg-amber-500/5 text-amber-300"
                  : "border border-sky-500/20 bg-sky-500/5 text-sky-300"
              }`}
            >
              {alert.message}
            </div>
          ))}
        </div>
      )}

      {/* Recent logs */}
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Recent Activity</p>
        <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg bg-slate-950/50 p-3 font-mono text-xs">
          {bodyguard.recent_logs.length === 0 ? (
            <p className="text-slate-600">No activity yet</p>
          ) : (
            bodyguard.recent_logs.slice(-8).reverse().map((log, i) => (
              <div key={i} className="flex gap-2">
                <span className="shrink-0 text-slate-600">
                  {new Date(log.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </span>
                <span
                  className={
                    log.level === "warning"
                      ? "text-amber-400"
                      : log.level === "error"
                      ? "text-red-400"
                      : "text-slate-400"
                  }
                >
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// ── Usage / Billing Widget ────────────────────────────────────────────────

function UsageWidget({ ec2Count, s3Count, dynamoCount, lambdaCount, runningEc2 }: {
  ec2Count: number;
  s3Count: number;
  dynamoCount: number;
  lambdaCount: number;
  runningEc2: number;
}) {
  const totalResources = ec2Count + s3Count + dynamoCount + lambdaCount;

  const usageItems = [
    {
      service: "EC2",
      count: ec2Count,
      detail: `${runningEc2} running`,
      color: "bg-sky-500",
    },
    {
      service: "S3",
      count: s3Count,
      detail: `${s3Count} active`,
      color: "bg-violet-500",
    },
    {
      service: "DynamoDB",
      count: dynamoCount,
      detail: `${dynamoCount} active`,
      color: "bg-emerald-500",
    },
    {
      service: "Lambda",
      count: lambdaCount,
      detail: `${lambdaCount} deployed`,
      color: "bg-amber-500",
    },
  ];

  const maxCount = Math.max(...usageItems.map((i) => i.count), 1);

  return (
    <div className="glass rounded-xl p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-500/10 text-sky-400">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" /></svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-white">Resource Usage</p>
          <p className="text-xs text-slate-500">{totalResources} resource{totalResources !== 1 ? "s" : ""} managed by Nimbus</p>
        </div>
      </div>

      <div className="space-y-3">
        {usageItems.map((item) => (
          <div key={item.service}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-300">{item.service}</span>
              <span className="text-xs text-slate-500">{item.detail}</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-slate-800">
              <div
                className={`h-1.5 rounded-full transition-all duration-500 ${item.color}`}
                style={{ width: `${item.count > 0 ? Math.max((item.count / maxCount) * 100, 8) : 0}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-lg bg-slate-800/50 border border-slate-700/50 p-3 text-center">
        <p className="text-xs text-slate-400 font-medium">Estimated monthly cost</p>
        <p className="text-xl font-bold text-white mt-0.5">
          {runningEc2 > 0 ? `~$${(runningEc2 * 8.50).toFixed(2)}` : "$0.00"}
        </p>
        <p className="text-[10px] text-slate-500 mt-0.5">
          {runningEc2 === 0 && totalResources === 0
            ? "No active resources"
            : runningEc2 <= 1
            ? "May be covered by free tier"
            : `${runningEc2} running instances`}
        </p>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDash = async () => {
      try {
        const res = await fetch(`${API}/dashboard`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setDashboard(await res.json());
        setError(null);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Cannot reach backend");
      } finally {
        setLoading(false);
      }
    };

    fetchDash();
    const id = setInterval(fetchDash, 10_000);
    return () => clearInterval(id);
  }, []);

  const allResources = dashboard
    ? [...dashboard.ec2, ...dashboard.s3, ...dashboard.dynamodb, ...dashboard.lambda]
    : [];

  const runningCount = dashboard?.ec2.filter((r) => r.state === "running").length ?? 0;
  const totalResources = allResources.filter((r) => !r.error).length;

  return (
    <AWSGate>
    <div className="min-h-screen bg-grid">
      <Navbar />

      <main className="mx-auto max-w-7xl px-6 pt-20 pb-12">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-8 flex items-end justify-between"
        >
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="mt-1 text-sm text-slate-400">
              Real-time view of your AWS resources managed by Nimbus
            </p>
          </div>
          <Link
            href="/chat"
            className="rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-500/20 transition hover:shadow-sky-500/35 hover:brightness-110"
          >
            + Deploy New
          </Link>
        </motion.div>

        {/* Error state */}
        {error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mb-8 rounded-xl border border-red-500/20 bg-red-500/5 p-6"
          >
            <p className="font-medium text-red-400">Cannot reach backend</p>
            <p className="mt-1 text-sm text-red-400/70">{error}</p>
            <p className="mt-3 text-xs text-red-400/50 font-mono">
              cd nimbus/backend && uvicorn main:app --reload --port 8000
            </p>
          </motion.div>
        )}

        {/* Loading state */}
        {loading && !error && (
          <div className="flex flex-col items-center justify-center py-32">
            <div className="flex gap-1.5">
              <span className="h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:0ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:150ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:300ms]" />
            </div>
            <p className="mt-4 text-sm text-slate-500">Connecting to Nimbus backend...</p>
          </div>
        )}

        {dashboard && !error && (
          <>
            {/* Stats row */}
            <motion.div
              custom={0}
              variants={fadeIn}
              initial="hidden"
              animate="visible"
              className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4"
            >
              <StatCard
                label="Total Resources"
                value={totalResources}
                icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z" /></svg>}
                color="text-white"
              />
              <StatCard
                label="Running Instances"
                value={runningCount}
                icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg>}
                color="text-emerald-400"
              />
              <StatCard
                label="Active Alerts"
                value={dashboard.bodyguard.unread_alerts.length}
                icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>}
                color={dashboard.bodyguard.unread_alerts.length > 0 ? "text-amber-400" : "text-white"}
              />
              <StatCard
                label="Auto-Stopped"
                value={dashboard.bodyguard.instances_stopped_total}
                icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" /></svg>}
                color="text-sky-400"
              />
            </motion.div>

            <div className="grid gap-8 lg:grid-cols-3">
              {/* Resources (2/3 width) */}
              <div className="lg:col-span-2">
                {totalResources === 0 ? (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-700 py-20 text-center"
                  >
                    <svg className="mb-4 h-12 w-12 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z" /></svg>
                    <p className="text-lg font-medium text-slate-400">No resources yet</p>
                    <p className="mt-1 text-sm text-slate-600">
                      Head to the chat to deploy your first AWS resource
                    </p>
                    <Link
                      href="/chat"
                      className="mt-6 rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-500/20 transition hover:brightness-110"
                    >
                      Start Building
                    </Link>
                  </motion.div>
                ) : (
                  <div className="space-y-6">
                    {dashboard.ec2.length > 0 && (
                      <motion.section custom={1} variants={fadeIn} initial="hidden" animate="visible">
                        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                          EC2 Instances
                        </h2>
                        <div className="grid gap-4 sm:grid-cols-2">
                          {dashboard.ec2.map((r) => (
                            <ResourceCard key={r.id} resource={r} />
                          ))}
                        </div>
                      </motion.section>
                    )}

                    {dashboard.s3.length > 0 && (
                      <motion.section custom={2} variants={fadeIn} initial="hidden" animate="visible">
                        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                          S3 Buckets
                        </h2>
                        <div className="grid gap-4 sm:grid-cols-2">
                          {dashboard.s3.map((r) => (
                            <ResourceCard key={r.id} resource={r} />
                          ))}
                        </div>
                      </motion.section>
                    )}

                    {dashboard.dynamodb.length > 0 && (
                      <motion.section custom={3} variants={fadeIn} initial="hidden" animate="visible">
                        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                          DynamoDB Tables
                        </h2>
                        <div className="grid gap-4 sm:grid-cols-2">
                          {dashboard.dynamodb.map((r) => (
                            <ResourceCard key={r.id} resource={r} />
                          ))}
                        </div>
                      </motion.section>
                    )}

                    {dashboard.lambda.length > 0 && (
                      <motion.section custom={4} variants={fadeIn} initial="hidden" animate="visible">
                        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                          Lambda Functions
                        </h2>
                        <div className="grid gap-4 sm:grid-cols-2">
                          {dashboard.lambda.map((r) => (
                            <ResourceCard key={r.id} resource={r} />
                          ))}
                        </div>
                      </motion.section>
                    )}
                  </div>
                )}
              </div>

              {/* Sidebar (1/3 width) */}
              <div className="space-y-6">
                <motion.div custom={2} variants={fadeIn} initial="hidden" animate="visible">
                  <UsageWidget
                    ec2Count={dashboard!.ec2.filter((r) => !r.error).length}
                    s3Count={dashboard!.s3.filter((r) => !r.error).length}
                    dynamoCount={dashboard!.dynamodb.filter((r) => !r.error).length}
                    lambdaCount={dashboard!.lambda.filter((r) => !r.error).length}
                    runningEc2={runningCount}
                  />
                </motion.div>
                <motion.div custom={3} variants={fadeIn} initial="hidden" animate="visible">
                  <BodyguardPanel bodyguard={dashboard.bodyguard} />
                </motion.div>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
    </AWSGate>
  );
}
