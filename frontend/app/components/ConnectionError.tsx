"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowClockwise, CloudSlash } from "@phosphor-icons/react";

/**
 * The state to show when the frontend can't reach the backend.
 *
 * It used to print `cd nimbus/backend && uvicorn main:app ...` at the user —
 * an instruction only the person who wrote the code could act on, and one that
 * leaks the deployment shape to everyone else. A customer needs three things
 * instead: what broke, whether their infrastructure is at risk, and a way to
 * act. The raw error still matters when the customer is the operator, so it
 * stays — folded into a disclosure rather than presented as the headline.
 *
 * Not styled as a red alarm: an unreachable API is a transient connection
 * state, and dashboards that flash red every time a poll misses train people
 * to ignore red. It sits in the page's cold palette with one warm-ish accent
 * on the icon.
 */
export default function ConnectionError({
  detail,
  onRetry,
  retryInSeconds,
}: {
  /** Raw error text (e.g. "HTTP 502"). Shown only under the disclosure. */
  detail?: string | null;
  /** Retry now. Omit to render without the action. */
  onRetry?: () => void;
  /** Seconds between automatic retries, if the caller polls. */
  retryInSeconds?: number;
}) {
  const [countdown, setCountdown] = useState(retryInSeconds ?? 0);

  // Counting down makes an automatic retry legible — without it the card looks
  // frozen and people mash the button.
  useEffect(() => {
    if (!retryInSeconds) return;
    setCountdown(retryInSeconds);
    const id = setInterval(
      () => setCountdown((s) => (s <= 1 ? retryInSeconds : s - 1)),
      1000,
    );
    return () => clearInterval(id);
  }, [retryInSeconds]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      role="status"
      className="glass mb-8 overflow-hidden rounded-2xl border-iris-500/20 p-6"
    >
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <div className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-iris-500/10 text-iris-300">
          <CloudSlash size={22} weight="duotone" />
        </div>

        <div className="min-w-0 flex-1">
          <h2 className="font-display text-lg font-semibold text-white">
            Can&rsquo;t reach Nimbus
          </h2>
          <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-slate-400">
            Your AWS resources are running normally — this only affects the view.
            Nimbus keeps trying in the background
            {countdown > 0 ? (
              <>
                {" "}
                and will check again in{" "}
                <span className="tabular-nums text-slate-200">{countdown}s</span>
              </>
            ) : null}
            .
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="btn-ion inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold text-white"
              >
                <ArrowClockwise size={16} weight="bold" />
                Check again
              </button>
            )}

            {detail && (
              <details className="group min-w-0">
                <summary className="cursor-pointer list-none rounded-full border border-slate-700/70 px-4 py-2 text-xs font-medium text-slate-400 transition-colors hover:border-slate-500 hover:text-slate-200">
                  Technical details
                </summary>
                <p className="mt-3 max-w-full overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 font-mono text-xs text-slate-400">
                  {detail}
                </p>
              </details>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
