"use client";

export function NimbusIcon({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <div
      className={`flex items-center justify-center rounded-xl bg-slate-900 shadow-lg shadow-ion-500/20 ring-1 ring-ion-500/20 ${className}`}
      style={{ width: size, height: size }}
    >
      <svg
        width={size * 0.6}
        height={size * 0.6}
        viewBox="0 0 30 30"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Three offset bars — reads as both "N" and layered atmosphere */}
        <rect x="4" y="8" width="22" height="5" rx="2.5" fill="#2E9EE0" />
        <rect x="4" y="15" width="15" height="5" rx="2.5" fill="#EDEFF3" opacity="0.85" />
        <rect x="4" y="22" width="9" height="4" rx="2" fill="#EDEFF3" opacity="0.5" />
      </svg>
    </div>
  );
}

export function NimbusWordmark({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <NimbusIcon size={size} />
      <span
        className="font-semibold text-white"
        style={{ fontSize: size * 0.56 }}
      >
        Nimbus AI
      </span>
    </div>
  );
}
