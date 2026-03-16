"use client";

import { SignUp } from "@clerk/nextjs";
import { motion } from "framer-motion";
import Link from "next/link";
import { NimbusIcon } from "../../components/NimbusLogo";

export default function SignUpPage() {
  return (
    <div className="relative flex min-h-screen">
      {/* ── Left panel: branding ── */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-gradient-to-br from-slate-900 via-sky-950 to-slate-900 p-12 lg:flex">
        <div className="pointer-events-none absolute inset-0">
          <div className="animate-float-slow absolute -top-32 -left-32 h-[500px] w-[500px] rounded-full bg-sky-500/10 blur-3xl" />
          <div className="animate-float absolute -bottom-32 -right-32 h-[400px] w-[400px] rounded-full bg-cyan-500/10 blur-3xl" />
          <div className="animate-float-reverse absolute top-1/2 left-1/2 h-[300px] w-[300px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-500/5 blur-3xl" />
        </div>

        <Link href="/" className="relative z-10 flex items-center gap-3">
          <NimbusIcon size={40} />
          <span className="text-xl font-semibold text-white">Nimbus AI</span>
        </Link>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.6 }}
          className="relative z-10"
        >
          <h1 className="text-4xl font-bold leading-tight text-white xl:text-5xl">
            Start building
            <br />
            <span className="text-shimmer">in seconds.</span>
          </h1>
          <p className="mt-4 max-w-md text-lg text-slate-400">
            No AWS expertise needed. Describe what you want and let our AI
            agents handle the complexity.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            {["Amazon Nova AI", "Real-time Monitoring", "Cost Protection"].map(
              (feature) => (
                <span
                  key={feature}
                  className="rounded-full border border-sky-500/20 bg-sky-500/10 px-4 py-1.5 text-sm text-sky-300"
                >
                  {feature}
                </span>
              )
            )}
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, duration: 0.6 }}
          className="relative z-10"
        >
          <div className="border-l-2 border-sky-500/30 pl-4">
            <p className="text-sm italic text-slate-400">
              &ldquo;I just wanted to host a project. AWS had 200+ services and
              I ended up with surprise charges. Nimbus AI exists so nobody has to
              go through that.&rdquo;
            </p>
            <p className="mt-2 text-xs text-slate-500">— The Nimbus AI Team</p>
          </div>
        </motion.div>
      </div>

      {/* ── Right panel: auth ── */}
      <div className="relative flex w-full flex-col items-center justify-center bg-slate-950 px-6 lg:w-1/2">
        <div className="bg-grid pointer-events-none absolute inset-0" />

        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-10 lg:hidden"
        >
          <Link href="/" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-cyan-400 text-base font-bold text-white shadow-lg shadow-sky-500/25">
              N
            </div>
            <span className="text-xl font-semibold text-white">Nimbus AI</span>
          </Link>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, duration: 0.5 }}
          className="relative z-10 w-full max-w-md"
        >
          <SignUp
            routing="path"
            path="/signup"
            signInUrl="/login"
          />

          <p className="mt-6 text-center text-xs text-slate-600">
            By signing up you agree to our terms of service
          </p>
        </motion.div>
      </div>
    </div>
  );
}
