"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { NimbusIcon } from "./NimbusLogo";
import { useAuthFetch } from "../lib/useAuthFetch";

const API = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api`;

interface AWSGateProps {
  children: React.ReactNode;
}

export default function AWSGate({ children }: AWSGateProps) {
  const authFetch = useAuthFetch();
  // A returning user who was connected last time almost certainly still is —
  // render immediately from that cached signal instead of blocking every single
  // page load behind a fresh round-trip, then confirm/correct in the background.
  // Measured: this removes ~250ms of pure sequential dead time before the chat
  // page (and its own session/dashboard fetches) can even start loading.
  const [status, setStatus] = useState<"loading" | "connected" | "disconnected" | "error">(() =>
    typeof window !== "undefined" && localStorage.getItem("nimbus_aws_connected") === "true"
      ? "connected"
      : "loading"
  );

  useEffect(() => {
    const check = async () => {
      try {
        const res = await authFetch(`${API}/settings/aws`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        const connected = !!data.connected;
        setStatus(connected ? "connected" : "disconnected");
        localStorage.setItem("nimbus_aws_connected", connected ? "true" : "false");
      } catch {
        // A transient blip shouldn't kick an already-optimistically-rendered
        // returning user back to a full-page error — only show it if we had
        // no good cached signal to begin with.
        setStatus((prev) => (prev === "connected" ? prev : "error"));
      }
    };
    check();
  }, []);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-grid">
        <div className="flex flex-col items-center gap-4">
          <div className="flex gap-1.5">
            <span className="h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:0ms]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:150ms]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:300ms]" />
          </div>
          <p className="text-sm text-slate-500">Checking AWS connection...</p>
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-grid">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass max-w-md rounded-2xl p-8 text-center"
        >
          <div className="mb-4 text-4xl">⚠️</div>
          <h2 className="text-xl font-bold text-white">Something went wrong</h2>
          <p className="mt-2 text-sm text-slate-400">
            We couldn&apos;t load your account right now. This is usually temporary —
            please try again in a moment.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-6 rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 px-6 py-2.5 text-sm font-semibold text-white transition hover:brightness-110"
          >
            Retry
          </button>
        </motion.div>
      </div>
    );
  }

  if (status === "disconnected") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-grid">
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="animate-float-slow absolute -top-40 right-[10%] h-[400px] w-[400px] rounded-full bg-sky-500/[0.07] blur-3xl" />
          <div className="animate-float absolute -bottom-32 left-[10%] h-[400px] w-[400px] rounded-full bg-violet-500/[0.05] blur-3xl" />
        </div>

        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5 }}
          className="relative z-10 max-w-lg text-center"
        >
          <div className="mb-6 flex justify-center">
            <NimbusIcon size={56} />
          </div>

          <h1 className="text-3xl font-bold text-white">Welcome to Nimbus AI</h1>
          <p className="mt-3 text-base text-slate-400">
            Before you can start deploying, you need to connect your AWS account.
          </p>

          <div className="mt-8 glass rounded-xl p-6 text-left">
            <h3 className="mb-4 text-sm font-semibold text-white">Quick setup (2 minutes)</h3>
            <ol className="space-y-3 text-sm text-slate-400">
              <li className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-xs font-bold text-sky-400">
                  1
                </span>
                <span>
                  Copy your unique <span className="text-slate-300">External ID</span> from the
                  Settings page
                </span>
              </li>
              <li className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-xs font-bold text-sky-400">
                  2
                </span>
                <span>
                  Deploy our <span className="text-slate-300">CloudFormation template</span> in your
                  AWS account, pasting in that External ID
                </span>
              </li>
              <li className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-xs font-bold text-sky-400">
                  3
                </span>
                <span>
                  Copy the stack&apos;s <span className="text-slate-300">Role ARN</span> output and
                  paste it into Settings
                </span>
              </li>
            </ol>
          </div>

          <Link
            href="/settings"
            className="mt-8 inline-block rounded-2xl bg-gradient-to-r from-sky-500 to-cyan-400 px-8 py-3.5 text-base font-semibold text-white shadow-xl shadow-sky-500/25 transition hover:shadow-sky-500/40 hover:brightness-110"
          >
            Connect AWS Account
          </Link>

          <p className="mt-4 text-xs text-slate-600">
            Nimbus never sees or stores a long-lived AWS key — only short-lived, expiring
            credentials it requests when it needs to act on your account
          </p>
        </motion.div>
      </div>
    );
  }

  return <>{children}</>;
}
