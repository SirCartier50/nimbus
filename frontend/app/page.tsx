"use client";

import { useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import Link from "next/link";
import { ArrowRight } from "@phosphor-icons/react";
import { NimbusIcon } from "./components/NimbusLogo";
import { ArchitectIcon, BodyguardIcon, ExecutorIcon } from "./components/AgentIcons";
import LoomBackground from "./components/LoomBackground";

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
    Icon: ArchitectIcon,
    description:
      "Translates your plain English into production-ready AWS architecture. Need to stay within free tier? Just say so, and it adapts to your constraints and budget.",
  },
  {
    title: "Executor",
    Icon: ExecutorIcon,
    description:
      "Once you approve the plan, Executor provisions real AWS resources: EC2 instances, S3 buckets, DynamoDB tables, Lambda functions, deployed in seconds, not hours.",
  },
  {
    title: "Bodyguard",
    Icon: BodyguardIcon,
    description:
      "Runs 24/7 in the background. Monitors resource usage, auto-stops idle instances, and tracks your spending against budget limits. No surprise bills.",
  },
];

// ── Chat preview ──────────────────────────────────────────────────────────
// A real preview of the actual chat interface (same bubble/avatar/plan-card
// treatment as /chat), not a fabricated terminal window.

function ChatPreview() {
  const planSteps = [
    { label: "Lambda function", detail: "api-handler", kind: "fn" as const },
    { label: "DynamoDB table", detail: "app-data", kind: "db" as const },
    { label: "S3 bucket", detail: "static-assets", kind: "s3" as const },
  ];

  // Each resource kind gets its own token color, like syntax highlighting —
  // not everything rendered in the same flat gray.
  const kindColor: Record<"fn" | "db" | "s3", string> = {
    fn: "text-amber-400",
    db: "text-emerald-400",
    s3: "text-ion-400",
  };

  const StepIcon = ({ kind }: { kind: "fn" | "db" | "s3" }) => {
    if (kind === "s3")
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
          <path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" />
        </svg>
      );
    if (kind === "db")
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path d="M4 7v10c0 2.21 3.58 4 8 4s8-1.79 8-4V7" />
          <ellipse cx="12" cy="7" rx="8" ry="4" />
          <path d="M4 12c0 2.21 3.58 4 8 4s8-1.79 8-4" />
        </svg>
      );
    return <span className="text-xs font-bold font-mono">fn</span>;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 1.2, duration: 0.8 }}
      className="glass w-full rounded-2xl p-6 text-left"
    >
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl bg-slate-800 px-4 py-2.5 text-sm leading-relaxed text-slate-100">
          I need a scalable API with a database
        </div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.7, duration: 0.4 }}
        className="mt-4 flex gap-3"
      >
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-ion-500 to-ion-400 text-[10px] font-bold text-white">
          N
        </div>
        <div className="min-w-0 flex-1 text-sm leading-relaxed text-slate-200">
          <p>Here is a plan that fits a small, low-traffic API.</p>
          <div className="mt-3 rounded-xl border border-ion-500/20 bg-ion-500/5 p-4">
            <div className="space-y-2">
              {planSteps.map((step, i) => (
                <motion.div
                  key={step.label}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 2.1 + i * 0.15, duration: 0.35 }}
                  className="flex items-start gap-3 rounded-lg bg-slate-800/50 p-3"
                >
                  <span className={`mt-0.5 ${kindColor[step.kind]}`}>
                    <StepIcon kind={step.kind} />
                  </span>
                  <div>
                    <p className="text-sm font-medium text-white">{step.label}</p>
                    <p className={`mt-0.5 font-mono text-xs ${kindColor[step.kind]}`}>{step.detail}</p>
                  </div>
                </motion.div>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
              <span>
                Est. cost: <span className="text-slate-300">$0/mo (free tier)</span>
              </span>
              <button className="rounded-lg bg-ion-700 px-3 py-1.5 text-xs font-semibold text-white">
                Deploy
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────

// Real, checkable claims only — no invented precision.
const stats = [
  { label: "AI Agents", value: "3" },
  { label: "AWS Resource Types", value: "15+" },
  { label: "Cost Estimate", value: "before every deploy" },
  { label: "Approval", value: "always yours" },
];

// ── Page ──────────────────────────────────────────────────────────────────

export default function HeroPage() {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();

  // Signed-in users never need the marketing page again — send them straight
  // to the app instead of making them look at a hero pitch every time.
  useEffect(() => {
    if (isLoaded && isSignedIn) router.replace("/dashboard");
  }, [isLoaded, isSignedIn, router]);

  if (!isLoaded || isSignedIn) return null;

  return (
    <div className="bg-grain relative min-h-screen">
      {/* ── Navbar ── */}
      <nav className="glass fixed top-0 z-50 w-full">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center gap-3">
            <NimbusIcon size={36} />
            <span className="whitespace-nowrap text-lg font-semibold text-white">Nimbus AI</span>
          </Link>

          <div className="flex items-center gap-4">
            {/* Redundant with "Start Building" (same destination) — drop it on
                phones so the wordmark doesn't wrap. */}
            <Link
              href="/login"
              className="hidden rounded-full px-5 py-2 text-sm font-medium text-slate-300 transition hover:text-white sm:inline-block"
            >
              Sign In
            </Link>
            <Link
              href="/login"
              className="rounded-full bg-ion-700 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-ion-500/25 transition hover:brightness-110 active:scale-[0.97]"
            >
              Start Building
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero section ── */}
      {/* Asymmetric split, not a centered stack: copy anchors the left, the
          chat preview is a real right-hand visual, not an add-on below the fold. */}
      <section className="relative mx-auto grid max-w-7xl grid-cols-1 gap-12 px-6 pt-24 pb-12 lg:grid-cols-2 lg:items-center lg:gap-8 lg:pt-32">
        <LoomBackground />
        <div className="text-center lg:text-left">
          <motion.div
            custom={0}
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            className="mb-8 inline-flex items-center gap-2 rounded-full border border-slate-700/80 bg-slate-900/60 px-3.5 py-1 text-xs font-medium text-slate-300"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-ion-400" aria-hidden />
            Every deploy is cost-estimated and human-approved
          </motion.div>

          {/* Monochrome by design — no gradient, no accent on the type. The
              headline carries the hero on size and weight alone; the only
              color in the hero is the loom mesh and the primary CTA. */}
          <motion.h1
            custom={1}
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            className="font-display text-6xl font-extrabold leading-[1.02] tracking-[-0.03em] text-white sm:text-7xl"
          >
            Deploy AWS in plain English.
          </motion.h1>

          <motion.p
            custom={2}
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            className="mt-6 max-w-lg text-lg text-slate-400 sm:text-xl lg:mx-0"
          >
            Three AI agents design, deploy, and protect your cloud infrastructure.
            Describe your budget and constraints, and Nimbus handles the rest.
          </motion.p>

          <motion.div
            custom={3}
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            className="mt-10 flex flex-wrap items-center justify-center gap-4 overflow-visible lg:justify-start"
          >
            <Link
              href="/login"
              className="group inline-flex items-center gap-2 rounded-full bg-ion-700 px-7 py-3.5 text-base font-semibold text-white shadow-lg shadow-ion-500/25 transition hover:brightness-110 active:scale-[0.97]"
            >
              Start Building
              <ArrowRight size={18} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
            </Link>
            <a
              href="#agents"
              className="group inline-flex items-center gap-2 rounded-full border border-slate-700 px-7 py-3.5 text-base font-medium text-slate-300 transition hover:border-slate-500 hover:text-white active:scale-[0.97]"
            >
              How It Works
              <ArrowRight size={18} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
            </a>
          </motion.div>

          {/* Quiet, tabular stat line instead of a boxed stats card — real
              numbers stated plainly, not shouted. */}
          <motion.div
            custom={4}
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            className="mt-10 flex flex-wrap justify-center gap-x-6 gap-y-2 font-mono text-xs text-slate-500 lg:justify-start"
          >
            {stats.map((s) => (
              <span key={s.label}>
                {s.label} <span className="text-slate-300 tabular-nums">{s.value}</span>
              </span>
            ))}
          </motion.div>
        </div>

        {/* Chat preview — the hero's visual, not a stacked afterthought */}
        <ChatPreview />
      </section>

      {/* ── Agents section ── */}
      <section id="agents" className="relative mx-auto max-w-7xl px-6 py-20">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mb-16 text-center"
        >
          {/* One gradient moment per page (the hero) — section headers stay quiet. */}
          <h2 className="font-display text-3xl font-bold text-white sm:text-4xl">
            Meet the agents
          </h2>
          <p className="mt-4 text-lg text-slate-400">
            Each one handles a distinct part of your cloud workflow.
          </p>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-5">
          {/* Architect gets a featured, larger treatment — it's the entry point,
              everything else follows from it. Deliberately asymmetric instead of
              three identical boxes. */}
          {(() => {
            const featured = agents[0];
            const FeaturedIcon = featured.Icon;
            return (
              <motion.div
                custom={0}
                variants={scaleIn}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="group glass rounded-2xl border-ion-500/20 p-10 transition-all duration-300 hover:border-ion-400/40 glow-blue-hover md:col-span-3"
              >
                <div className="mb-6 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-ion-500/10 text-ion-400 shadow-lg transition-shadow group-hover:shadow-ion-500/20">
                  <FeaturedIcon size={32} />
                </div>
                <h3 className="font-display mb-3 text-2xl font-semibold text-white">
                  {featured.title} Agent
                </h3>
                <p className="max-w-md text-base leading-relaxed text-slate-400">
                  {featured.description}
                </p>
              </motion.div>
            );
          })()}

          <div className="flex flex-col gap-6 md:col-span-2">
            {agents.slice(1).map((agent, i) => (
              <motion.div
                key={agent.title}
                custom={i + 1}
                variants={scaleIn}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="group glass flex-1 rounded-2xl border-ion-500/20 p-6 transition-all duration-300 hover:border-ion-400/40 glow-blue-hover"
              >
                <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl bg-ion-500/10 text-ion-400 shadow-lg transition-shadow group-hover:shadow-ion-500/20">
                  <agent.Icon size={22} />
                </div>
                <h3 className="mb-2 text-lg font-semibold text-white">
                  {agent.title} Agent
                </h3>
                <p className="text-sm leading-relaxed text-slate-400">
                  {agent.description}
                </p>
              </motion.div>
            ))}
          </div>
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
          <h2 className="font-display text-3xl font-bold text-white sm:text-4xl">
            How it works
          </h2>
        </motion.div>

        <div className="relative space-y-12">
          {/* Connecting line */}
          <div className="absolute left-8 top-0 hidden h-full w-px bg-ion-500/40 sm:block" />

          {[
            {
              step: "01",
              title: "Describe what you need",
              desc: 'Just type something like "I need a web server with a database" in plain English.',
            },
            {
              step: "02",
              title: "Review the plan",
              desc: "The Architect agent designs the right architecture for your needs and shows you a real cost estimate before anything is built.",
            },
            {
              step: "03",
              title: "Approve and deploy",
              desc: "One click and the Executor agent provisions real AWS resources in your account within seconds.",
            },
            {
              step: "04",
              title: "Stay protected",
              desc: "The Bodyguard agent monitors everything 24/7, stops idle resources, and keeps your spending in check.",
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
              <div className="relative z-10 flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-ion-700 text-lg font-bold text-white shadow-lg shadow-ion-500/25">
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
      {/* A full-strength accent block instead of another dark glass card — one
          genuine bold moment on the page instead of the accent staying at
          10-20% opacity everywhere. */}
      <section className="relative mx-auto max-w-4xl px-6 py-20 text-center">
        <p className="mb-6 text-lg text-slate-400">
          No AWS expertise needed. Just describe what you want to build.
        </p>
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="bg-grain relative overflow-hidden rounded-3xl bg-gradient-to-br from-ion-500 to-ion-700 px-8 py-16"
        >
          <h2 className="font-display relative z-[1] text-3xl font-bold text-white sm:text-4xl">
            Ready to deploy your first resource?
          </h2>
          <Link
            href="/login"
            className="relative z-[1] mt-8 inline-block rounded-2xl bg-white px-10 py-4 text-lg font-semibold text-ion-700 shadow-xl transition hover:brightness-95 active:scale-[0.97]"
          >
            Start Building
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
        </div>
      </footer>
    </div>
  );
}
