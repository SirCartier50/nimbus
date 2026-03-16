"use client";

export function NimbusIcon({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <div
      className={`flex items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-cyan-400 shadow-lg shadow-sky-500/25 ${className}`}
      style={{ width: size, height: size }}
    >
      <svg
        width={size * 0.6}
        height={size * 0.6}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Cloud shape */}
        <path
          d="M6.5 19C4.01 19 2 16.99 2 14.5C2 12.5 3.4 10.8 5.28 10.25C5.57 7.34 8.02 5 11 5C13.45 5 15.55 6.6 16.36 8.85C16.57 8.82 16.78 8.8 17 8.8C19.76 8.8 22 11.04 22 13.8C22 16.56 19.76 18.8 17 18.8L6.5 19Z"
          fill="white"
          fillOpacity="0.95"
        />
        {/* Lightning bolt accent */}
        <path
          d="M13 11L10.5 14.5H13L11 18"
          stroke="rgba(14,165,233,0.8)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
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
