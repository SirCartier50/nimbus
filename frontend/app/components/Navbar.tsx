"use client";

import { useUser, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NimbusIcon } from "./NimbusLogo";

const navLinks = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/chat", label: "Chat" },
  { href: "/services", label: "Services" },
  { href: "/settings", label: "Settings" },
];

export default function Navbar() {
  const pathname = usePathname();
  const { user } = useUser();

  return (
    <nav className="glass fixed top-0 z-50 w-full">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        {/* Logo + nav links */}
        <div className="flex items-center gap-8">
          <Link href="/dashboard" className="flex items-center gap-3">
            <NimbusIcon size={32} />
            <span className="text-lg font-semibold text-white">Nimbus AI</span>
          </Link>

          <div className="flex items-center gap-1">
            {navLinks.map((link) => {
              const isActive = pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                    isActive
                      ? "bg-sky-500/10 text-sky-300"
                      : "text-slate-400 hover:bg-slate-800/50 hover:text-white"
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </div>
        </div>

        {/* User button */}
        <div className="flex items-center gap-3">
          {user && (
            <span className="text-sm text-slate-300">
              {user.firstName || user.emailAddresses[0]?.emailAddress?.split("@")[0]}
            </span>
          )}
          <UserButton
            appearance={{
              elements: {
                avatarBox: "h-8 w-8 ring-2 ring-sky-500/30",
              },
            }}
          />
        </div>
      </div>
    </nav>
  );
}
