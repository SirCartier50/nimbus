"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import { motion } from "framer-motion";
import Link from "next/link";
import { NimbusIcon } from "./components/NimbusLogo";

// ── Animation variants ────────────────────────────────────────────────────

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.15, duration: 0.6, ease: "easeOut" as const },
  }),
};

const scaleIn = {
  hidden: { opacity: 0, scale: 0.9 },
  visible: (i: number) => ({
    opacity: 1,
    scale: 1,
    transition: { delay: 0.6 + i * 0.15, duration: 0.5, ease: "easeOut" as const },
  }),
};

// ── Agent data ────────────────────────────────────────────────────────────

const agents = [
  {
    title: "Architect",
    icon: "🧠",
    color: "from-sky-500 to-cyan-400",
    border: "border-sky-500/20 hover:border-sky-400/40",
    glow: "group-hover:shadow-sky-500/20",
    description:
      "Powered by Amazon Nova. Translates your plain English into production-ready AWS architecture. Need to stay within free tier? Just say so — it adapts to your constraints and budget.",
  },
  {
    title: "Executor",
    icon: "⚡",
    color: "from-violet-500 to-purple-400",
    border: "border-violet-500/20 hover:border-violet-400/40",
    glow: "group-hover:shadow-violet-500/20",
    description:
      "Once you approve the plan, Executor provisions real AWS resources — EC2 instances, S3 buckets, DynamoDB tables, Lambda functions — deployed in seconds, not hours.",
  },
  {
    title: "Bodyguard",
    icon: "🛡️",
    color: "from-emerald-500 to-teal-400",
    border: "border-emerald-500/20 hover:border-emerald-400/40",
    glow: "group-hover:shadow-emerald-500/20",
    description:
      "Runs 24/7 in the background. Monitors resource usage, auto-stops idle instances, and tracks your spending against budget limits. No surprise bills.",
  },
];

// ── Floating cloud blobs ──────────────────────────────────────────────────

function CloudBlobs() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* Top-right blob */}
      <div className="animate-float-slow absolute -top-40 right-[-10%] h-[500px] w-[500px] rounded-full bg-sky-500/[0.07] blur-3xl" />
      {/* Left blob */}
      <div className="animate-float absolute -left-20 top-1/3 h-[400px] w-[400px] rounded-full bg-violet-500/[0.05] blur-3xl" />
      {/* Bottom center blob */}
      <div className="animate-float-reverse absolute -bottom-32 left-1/3 h-[500px] w-[500px] rounded-full bg-cyan-500/[0.06] blur-3xl" />
    </div>
  );
}

// ── Animated terminal demo ────────────────────────────────────────────────

function TerminalDemo() {
  const lines = [
    { type: "user", text: '> "I need a scalable API with a database"' },
    { type: "nimbus", text: "🧠 Architect: Designing infrastructure..." },
    { type: "plan", text: "   ├─ Lambda function (API handler)" },
    { type: "plan", text: "   ├─ DynamoDB table (data layer)" },
    { type: "plan", text: "   └─ S3 bucket (static assets)" },
    { type: "nimbus", text: "⚡ Executor: Deploying 3 resources..." },
    { type: "success", text: "✓  All resources live. Estimated cost: $0/mo (free tier)" },
    { type: "guard", text: "🛡️ Bodyguard: Monitoring active." },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 1.2, duration: 0.8 }}
      className="glass glow-blue mx-auto mt-16 max-w-2xl rounded-2xl p-1"
    >
      <div className="rounded-xl bg-slate-950/80 p-6">
        <div className="mb-4 flex items-center gap-2">
          <div className="h-3 w-3 rounded-full bg-red-500/60" />
          <div className="h-3 w-3 rounded-full bg-yellow-500/60" />
          <div className="h-3 w-3 rounded-full bg-green-500/60" />
          <span className="ml-2 text-xs text-slate-500 font-mono">nimbus terminal</span>
        </div>
        <div className="space-y-2 font-mono text-sm">
          {lines.map((line, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 1.6 + i * 0.3, duration: 0.4 }}
              className={
                line.type === "user"
                  ? "text-sky-300"
                  : line.type === "nimbus"
                  ? "text-slate-300"
                  : line.type === "plan"
                  ? "text-slate-500"
                  : line.type === "success"
                  ? "text-emerald-400"
                  : "text-violet-400"
              }
            >
              {line.text}
            </motion.div>
          ))}
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 1, 0] }}
            transition={{ delay: 4, duration: 1, repeat: Infinity }}
            className="inline-block text-sky-400"
          >
            █
          </motion.span>
        </div>
      </div>
    </motion.div>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────

const stats = [
  { label: "AI Agents", value: "3" },
  { label: "AWS Services", value: "5+" },
  { label: "Deploy Time", value: "~30s" },
  { label: "Cost Awareness", value: "Built In" },
];

// ── Page ──────────────────────────────────────────────────────────────────

export default function HeroPage() {
  const { isSignedIn } = useAuth();

  return (
    <div className="relative min-h-screen bg-grid">
      <CloudBlobs />

      {/* ── Navbar ── */}
      <nav className="glass fixed top-0 z-50 w-full">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center gap-3">
            <NimbusIcon size={36} />
            <span className="text-lg font-semibold text-white">Nimbus AI</span>
          </Link>

          <div className="flex items-center gap-4">
            {isSignedIn ? (
              <>
                <Link
                  href="/dashboard"
                  className="rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 transition hover:shadow-sky-500/40 hover:brightness-110"
                >
                  Dashboard
                </Link>
                <UserButton
                  appearance={{
                    elements: {
                      avatarBox: "h-8 w-8 ring-2 ring-sky-500/30",
                    },
                  }}
                />
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="rounded-xl px-5 py-2 text-sm font-medium text-slate-300 transition hover:text-white"
                >
                  Sign In
                </Link>
                <Link
                  href="/login"
                  className="rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 transition hover:shadow-sky-500/40 hover:brightness-110"
                >
                  Get Started
                </Link>
              </>
            )}
          </div>
        </div>
      </nav>

      {/* ── Hero section ── */}
      <section className="relative mx-auto flex max-w-7xl flex-col items-center px-6 pt-36 pb-12 text-center">
        <motion.div
          custom={0}
          variants={fadeUp}
          initial="hidden"
          animate="visible"
          className="mb-6 inline-flex items-center gap-2 rounded-full border border-sky-500/20 bg-sky-500/10 px-4 py-1.5 text-sm text-sky-300"
        >
          <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />
          Powered by Amazon Nova AI
        </motion.div>

        <motion.h1
          custom={1}
          variants={fadeUp}
          initial="hidden"
          animate="visible"
          className="max-w-4xl text-5xl font-bold leading-tight tracking-tight text-white sm:text-6xl lg:text-7xl"
        >
          Deploy AWS in{" "}
          <span className="text-shimmer">Plain English</span>
        </motion.h1>

        <motion.p
          custom={2}
          variants={fadeUp}
          initial="hidden"
          animate="visible"
          className="mt-6 max-w-2xl text-lg text-slate-400 sm:text-xl"
        >
          Three AI agents design, deploy, and protect your cloud infrastructure.
          Tell it your budget, your constraints, or just what you need — Nimbus handles the rest.
        </motion.p>

        <motion.div
          custom={3}
          variants={fadeUp}
          initial="hidden"
          animate="visible"
          className="mt-10 flex flex-wrap items-center justify-center gap-4 overflow-visible"
        >
          <Link
            href="/login"
            className="rounded-2xl bg-gradient-to-r from-sky-500 to-cyan-400 px-8 py-3.5 text-base font-semibold text-white shadow-lg shadow-sky-500/25 transition hover:shadow-sky-500/40 hover:brightness-110"
          >
            Start Building
          </Link>
          <a
            href="#agents"
            className="rounded-2xl border border-slate-700 px-8 py-3.5 text-base font-medium text-slate-300 transition hover:border-slate-500 hover:text-white"
          >
            How It Works
          </a>
        </motion.div>

        {/* Terminal demo */}
        <TerminalDemo />
      </section>

      {/* ── Stats ── */}
      <motion.section
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.6 }}
        className="mx-auto max-w-4xl px-6 py-16"
      >
        <div className="glass grid grid-cols-2 gap-6 rounded-2xl p-8 sm:grid-cols-4">
          {stats.map((s) => (
            <div key={s.label} className="text-center">
              <p className="text-3xl font-bold text-white">{s.value}</p>
              <p className="mt-1 text-sm text-slate-400">{s.label}</p>
            </div>
          ))}
        </div>
      </motion.section>

      {/* ── Agents section ── */}
      <section id="agents" className="relative mx-auto max-w-7xl px-6 py-20">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mb-16 text-center"
        >
          <h2 className="text-3xl font-bold text-white sm:text-4xl">
            Three Agents.{" "}
            <span className="text-gradient">One Mission.</span>
          </h2>
          <p className="mt-4 text-lg text-slate-400">
            Each agent handles a distinct part of your cloud workflow.
          </p>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-3">
          {agents.map((agent, i) => (
            <motion.div
              key={agent.title}
              custom={i}
              variants={scaleIn}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className={`group glass rounded-2xl p-8 transition-all duration-300 ${agent.border} glow-blue-hover`}
            >
              <div
                className={`mb-5 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br ${agent.color} text-2xl shadow-lg ${agent.glow} transition-shadow`}
              >
                {agent.icon}
              </div>
              <h3 className="mb-3 text-xl font-semibold text-white">
                {agent.title} Agent
              </h3>
              <p className="text-sm leading-relaxed text-slate-400">
                {agent.description}
              </p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="mx-auto max-w-5xl px-6 py-20">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mb-16 text-center"
        >
          <h2 className="text-3xl font-bold text-white sm:text-4xl">
            Cloud Made{" "}
            <span className="text-gradient">Simple</span>
          </h2>
        </motion.div>

        <div className="relative space-y-12">
          {/* Connecting line */}
          <div className="absolute left-8 top-0 hidden h-full w-px bg-gradient-to-b from-sky-500/50 via-violet-500/50 to-emerald-500/50 sm:block" />

          {[
            {
              step: "01",
              title: "Describe what you need",
              desc: 'Just type something like "I need a web server with a database" in plain English.',
              color: "bg-sky-500",
            },
            {
              step: "02",
              title: "Review the plan",
              desc: "The Architect agent uses Amazon Nova AI to design the optimal architecture for your needs — with full cost transparency.",
              color: "bg-violet-500",
            },
            {
              step: "03",
              title: "Approve and deploy",
              desc: "One click and the Executor agent provisions real AWS resources in your account within seconds.",
              color: "bg-emerald-500",
            },
            {
              step: "04",
              title: "Stay protected",
              desc: "The Bodyguard agent monitors everything 24/7, stops idle resources, and keeps your spending in check.",
              color: "bg-teal-500",
            },
          ].map((item, i) => (
            <motion.div
              key={item.step}
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1, duration: 0.5 }}
              className="flex items-start gap-6"
            >
              <div
                className={`relative z-10 flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl ${item.color} text-lg font-bold text-white shadow-lg`}
              >
                {item.step}
              </div>
              <div className="pt-2">
                <h3 className="text-lg font-semibold text-white">
                  {item.title}
                </h3>
                <p className="mt-1 text-sm text-slate-400">{item.desc}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── CTA section ── */}
      <section className="relative mx-auto max-w-4xl px-6 py-20 text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="glass glow-blue rounded-3xl px-8 py-16"
        >
          <h2 className="text-3xl font-bold text-white sm:text-4xl">
            Ready to deploy your first resource?
          </h2>
          <p className="mt-4 text-lg text-slate-400">
            No AWS expertise needed. Just describe what you want to build.
          </p>
          <Link
            href="/login"
            className="mt-8 inline-block rounded-2xl bg-gradient-to-r from-sky-500 to-cyan-400 px-10 py-4 text-lg font-semibold text-white shadow-xl shadow-sky-500/25 transition hover:shadow-sky-500/40 hover:brightness-110"
          >
            Get Started
          </Link>
        </motion.div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-slate-800/50 px-6 py-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-2">
            <NimbusIcon size={24} />
            <span className="text-sm text-slate-500">Nimbus AI</span>
          </div>
          <p className="text-sm text-slate-600">
            Built for the Amazon Nova AI Hackathon
          </p>
        </div>
      </footer>
    </div>
  );
}
