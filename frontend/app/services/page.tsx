"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Navbar from "../components/Navbar";

// ── Service data ──────────────────────────────────────────────────────────

interface Service {
  name: string;
  icon: string;
  category: string;
  short: string;
  description: string;
  useCases: string[];
  freeTier: string;
  pricing: string;
  nimbusSupport: "full" | "coming";
}

const services: Service[] = [
  {
    name: "EC2",
    icon: "🖥",
    category: "Compute",
    short: "Virtual Servers",
    description:
      "Elastic Compute Cloud gives you resizable virtual machines in the cloud. Think of it as renting a computer that runs 24/7 — you pick the size, operating system, and what software to install.",
    useCases: [
      "Hosting web applications and APIs",
      "Running backend servers",
      "Development and testing environments",
    ],
    freeTier: "750 hours/month of t2.micro or t3.micro for 12 months",
    pricing: "t2.micro: ~$8.50/month (free tier covers this fully)",
    nimbusSupport: "full",
  },
  {
    name: "S3",
    icon: "🪣",
    category: "Storage",
    short: "Object Storage",
    description:
      "Simple Storage Service is like an infinite hard drive in the cloud. Store any file — images, videos, backups, static websites. Files are organized in \"buckets\" and accessible via URLs.",
    useCases: [
      "Hosting static websites (HTML/CSS/JS)",
      "Storing user uploads and media",
      "Data backups and archiving",
    ],
    freeTier: "5 GB storage, 20,000 GET and 2,000 PUT requests/month for 12 months",
    pricing: "$0.023/GB/month after free tier",
    nimbusSupport: "full",
  },
  {
    name: "DynamoDB",
    icon: "🗄",
    category: "Database",
    short: "NoSQL Database",
    description:
      "A fully managed NoSQL database that scales automatically. No servers to manage, no patches to apply. You just define your data structure and start reading/writing. Great for apps that need fast, flexible data access.",
    useCases: [
      "User profiles and session data",
      "Real-time leaderboards and counters",
      "IoT device data and event logs",
    ],
    freeTier: "25 GB storage, 25 read/write capacity units (always free)",
    pricing: "On-demand: $1.25 per million writes, $0.25 per million reads",
    nimbusSupport: "full",
  },
  {
    name: "Lambda",
    icon: "λ",
    category: "Compute",
    short: "Serverless Functions",
    description:
      "Run code without thinking about servers. Upload a function, Lambda runs it when triggered — by an API call, a file upload, a timer, or dozens of other events. You only pay for the milliseconds your code actually runs.",
    useCases: [
      "API endpoints without managing servers",
      "Automated data processing pipelines",
      "Scheduled tasks (cron jobs in the cloud)",
    ],
    freeTier: "1 million requests and 400,000 GB-seconds/month (always free)",
    pricing: "$0.20 per million requests after free tier",
    nimbusSupport: "full",
  },
  {
    name: "CloudWatch",
    icon: "📊",
    category: "Monitoring",
    short: "Metrics & Logs",
    description:
      "AWS's built-in monitoring service. It collects metrics (CPU usage, request counts, errors) from all your resources and lets you set alarms. Nimbus's Bodyguard agent uses CloudWatch under the hood.",
    useCases: [
      "Monitoring server health and performance",
      "Setting alarms for high CPU or errors",
      "Collecting and searching application logs",
    ],
    freeTier: "10 custom metrics, 10 alarms, 5 GB log data/month (always free)",
    pricing: "$0.30 per metric/month after free tier",
    nimbusSupport: "full",
  },
  {
    name: "RDS",
    icon: "🐘",
    category: "Database",
    short: "Relational Database",
    description:
      "Managed relational databases — MySQL, PostgreSQL, MariaDB, and more. AWS handles backups, patching, and scaling. Good when your data has relationships (users → orders → products).",
    useCases: [
      "Traditional web app backends",
      "Applications with complex data relationships",
      "Migrating existing SQL databases to the cloud",
    ],
    freeTier: "750 hours/month of db.t2.micro for 12 months",
    pricing: "db.t3.micro: ~$12.50/month",
    nimbusSupport: "coming",
  },
  {
    name: "API Gateway",
    icon: "🚪",
    category: "Networking",
    short: "API Management",
    description:
      "A front door for your APIs. It handles routing, authentication, rate limiting, and caching so your Lambda functions or servers don't have to. Pairs perfectly with Lambda for fully serverless APIs.",
    useCases: [
      "Creating REST or WebSocket APIs",
      "Adding auth to existing endpoints",
      "Rate limiting and usage plans for API consumers",
    ],
    freeTier: "1 million API calls/month for 12 months",
    pricing: "$3.50 per million calls after free tier",
    nimbusSupport: "coming",
  },
  {
    name: "CloudFront",
    icon: "🌐",
    category: "Networking",
    short: "CDN",
    description:
      "A content delivery network that caches your content at edge locations worldwide. Your users get faster load times because content is served from a server near them, not from a single origin.",
    useCases: [
      "Speeding up static website delivery",
      "Caching API responses globally",
      "Streaming video and media content",
    ],
    freeTier: "1 TB data transfer out, 10M requests/month (always free)",
    pricing: "$0.085/GB after free tier",
    nimbusSupport: "coming",
  },
];

const categories = ["All", "Compute", "Storage", "Database", "Monitoring", "Networking"];

// ── Components ────────────────────────────────────────────────────────────

function ServiceCard({
  service,
  onClick,
}: {
  service: Service;
  onClick: () => void;
}) {
  return (
    <motion.button
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="glass group w-full rounded-xl p-6 text-left transition-all duration-200 hover:border-sky-500/30 glow-blue-hover"
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-800 text-xl">
            {service.icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-white">{service.name}</h3>
              {service.nimbusSupport === "full" ? (
                <span className="rounded-full bg-sky-500/15 border border-sky-500/25 px-2 py-0.5 text-[10px] font-medium text-sky-400">
                  Supported
                </span>
              ) : (
                <span className="rounded-full bg-slate-500/15 border border-slate-500/25 px-2 py-0.5 text-[10px] font-medium text-slate-400">
                  Coming Soon
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">{service.short}</p>
          </div>
        </div>
        <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs text-slate-400">
          {service.category}
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-slate-400 line-clamp-2">
        {service.description}
      </p>

      <div className="mt-3 flex items-center gap-2">
        <span className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-400">
          Free tier: {service.freeTier.split(" for")[0]}
        </span>
      </div>
    </motion.button>
  );
}

function ServiceModal({
  service,
  onClose,
}: {
  service: Service;
  onClose: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        onClick={(e) => e.stopPropagation()}
        className="glass w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl p-8"
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-slate-800 text-2xl">
              {service.icon}
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white">{service.name}</h2>
              <p className="text-sm text-slate-400">{service.short} · {service.category}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white transition"
          >
            ✕
          </button>
        </div>

        {/* What is it */}
        <section className="mb-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            What is it?
          </h3>
          <p className="text-sm leading-relaxed text-slate-300">{service.description}</p>
        </section>

        {/* Use cases */}
        <section className="mb-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Common use cases
          </h3>
          <ul className="space-y-2">
            {service.useCases.map((uc, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                <span className="mt-1 text-sky-400">›</span>
                {uc}
              </li>
            ))}
          </ul>
        </section>

        {/* Pricing */}
        <section className="mb-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Pricing
          </h3>
          <div className="space-y-2">
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3">
              <p className="text-xs font-medium text-emerald-400">Free Tier</p>
              <p className="mt-0.5 text-sm text-emerald-300">{service.freeTier}</p>
            </div>
            <div className="rounded-lg bg-slate-800/50 p-3">
              <p className="text-xs font-medium text-slate-400">After Free Tier</p>
              <p className="mt-0.5 text-sm text-slate-300">{service.pricing}</p>
            </div>
          </div>
        </section>

        {/* Nimbus support */}
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Nimbus Support
          </h3>
          {service.nimbusSupport === "full" ? (
            <div className="rounded-lg bg-sky-500/5 border border-sky-500/20 p-3">
              <p className="text-sm text-sky-300">
                Fully supported — you can deploy this service through the Nimbus chat.
                Just describe what you need and the Architect will include it in your plan.
              </p>
            </div>
          ) : (
            <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3">
              <p className="text-sm text-amber-300">
                Coming soon — this service will be available in a future update.
              </p>
            </div>
          )}
        </section>
      </motion.div>
    </motion.div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function ServicesPage() {
  const [filter, setFilter] = useState("All");
  const [selected, setSelected] = useState<Service | null>(null);

  const filtered =
    filter === "All"
      ? services
      : services.filter((s) => s.category === filter);

  return (
    <div className="min-h-screen bg-grid">
      <Navbar />

      <main className="mx-auto max-w-7xl px-6 pt-20 pb-12">
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-8"
        >
          <h1 className="text-2xl font-bold text-white">AWS Services</h1>
          <p className="mt-1 text-sm text-slate-400">
            Understand each service in plain English — what it does, what it costs, and when to use it
          </p>
        </motion.div>

        {/* Category filter */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1, duration: 0.3 }}
          className="mb-8 flex flex-wrap gap-2"
        >
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                filter === cat
                  ? "bg-sky-500/15 text-sky-300 border border-sky-500/25"
                  : "text-slate-400 border border-slate-700/50 hover:bg-slate-800/50 hover:text-white"
              }`}
            >
              {cat}
            </button>
          ))}
        </motion.div>

        {/* Supported count */}
        <div className="mb-6 flex items-center gap-4 text-xs text-slate-500">
          <span>
            <span className="text-sky-400 font-medium">{services.filter((s) => s.nimbusSupport === "full").length}</span> supported
          </span>
          <span>
            <span className="text-slate-400 font-medium">{services.filter((s) => s.nimbusSupport === "coming").length}</span> coming soon
          </span>
        </div>

        {/* Service grid */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((service, i) => (
            <motion.div
              key={service.name}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05, duration: 0.3 }}
            >
              <ServiceCard
                service={service}
                onClick={() => setSelected(service)}
              />
            </motion.div>
          ))}
        </div>

        {/* Info banner */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3, duration: 0.4 }}
          className="mt-12 glass rounded-xl p-6 text-center"
        >
          <p className="text-sm text-slate-400">
            Don&apos;t know which service to pick?{" "}
            <a href="/chat" className="text-sky-400 hover:text-sky-300 font-medium transition">
              Just tell the Architect what you want to build
            </a>{" "}
            and it will choose the right services for you.
          </p>
        </motion.div>
      </main>

      {/* Detail modal */}
      <AnimatePresence>
        {selected && (
          <ServiceModal
            service={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
