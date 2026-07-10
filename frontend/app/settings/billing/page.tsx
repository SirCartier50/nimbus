"use client";

import { motion } from "framer-motion";
import { PricingTable } from "@clerk/nextjs";
import Navbar from "../../components/Navbar";

export default function BillingPage() {
  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="mx-auto max-w-3xl px-6 pt-20 pb-12">
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-8"
        >
          <h1 className="font-display text-2xl font-bold text-white">Billing & Plan</h1>
          <p className="mt-1 text-sm text-slate-400">
            Manage your subscription and see what each plan includes.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05, duration: 0.4 }}
          className="glass rounded-xl p-6"
        >
          <PricingTable />
        </motion.div>
      </main>
    </div>
  );
}
