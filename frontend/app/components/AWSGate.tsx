"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { NimbusIcon } from "./NimbusLogo";

const API = "http://localhost:8000/api";

interface AWSGateProps {
  children: React.ReactNode;
}

export default function AWSGate({ children }: AWSGateProps) {
  const [status, setStatus] = useState<"loading" | "connected" | "disconnected" | "error">("loading");

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API}/settings/aws`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        setStatus(data.connected ? "connected" : "disconnected");
      } catch {
        setStatus("error");
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
          <h2 className="text-xl font-bold text-white">Backend Unavailable</h2>
          <p className="mt-2 text-sm text-slate-400">
            Cannot reach the Nimbus backend. Make sure it&apos;s running on port 8000.
          </p>
          <p className="mt-4 rounded-lg bg-slate-800/50 p-3 font-mono text-xs text-slate-500">
            uvicorn main:app --reload --port 8000
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

          <h1 className="text-3xl font-bold text-white">Welcome to Nimbus</h1>
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
                  Log into the{" "}
                  <span className="text-slate-300">AWS Console</span> and go to IAM → Users → Create User
                </span>
              </li>
              <li className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-xs font-bold text-sky-400">
                  2
                </span>
                <span>
                  Attach the <span className="text-slate-300 font-mono text-xs">PowerUserAccess</span> policy
                </span>
              </li>
              <li className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-xs font-bold text-sky-400">
                  3
                </span>
                <span>
                  Create an <span className="text-slate-300">Access Key</span> and paste the credentials in Settings
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
            Your credentials are encrypted and never stored on our servers
          </p>
        </motion.div>
      </div>
    );
  }

  return <>{children}</>;
}
