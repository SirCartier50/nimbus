"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { NimbusIcon } from "./components/NimbusLogo";

export default function NotFound() {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-grid">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="animate-float-slow absolute -top-40 right-[15%] h-[400px] w-[400px] rounded-full bg-sky-500/[0.06] blur-3xl" />
        <div className="animate-float absolute -bottom-32 left-[15%] h-[400px] w-[400px] rounded-full bg-violet-500/[0.04] blur-3xl" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="relative z-10 text-center"
      >
        <div className="mb-6 flex justify-center">
          <NimbusIcon size={48} />
        </div>

        <h1 className="text-8xl font-bold text-shimmer">404</h1>

        <p className="mt-4 text-xl font-medium text-white">
          This resource doesn&apos;t exist
        </p>
        <p className="mt-2 text-sm text-slate-400">
          Even our Architect agent couldn&apos;t find this page.
        </p>

        <div className="mt-8 flex items-center justify-center gap-4">
          <Link
            href="/"
            className="rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-sky-500/20 transition hover:brightness-110"
          >
            Go Home
          </Link>
          <Link
            href="/dashboard"
            className="rounded-xl border border-slate-700 px-6 py-2.5 text-sm font-medium text-slate-300 transition hover:border-slate-500 hover:text-white"
          >
            Dashboard
          </Link>
        </div>
      </motion.div>
    </div>
  );
}
