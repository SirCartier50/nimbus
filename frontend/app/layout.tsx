import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Nimbus AI — Deploy AWS in Plain English",
  description:
    "AI-powered AWS infrastructure manager. Three intelligent agents design, deploy, and protect your cloud.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider
      appearance={{
        baseTheme: dark,
        variables: {
          colorPrimary: "#38bdf8",
          colorBackground: "#0f172a",
          colorInputBackground: "#1e293b",
          colorInputText: "#f8fafc",
          colorText: "#f8fafc",
          colorTextSecondary: "#cbd5e1",
          colorNeutral: "#f8fafc",
          colorDanger: "#f87171",
          borderRadius: "0.75rem",
        },
        elements: {
          rootBox: "w-full",
          card: "!bg-transparent !shadow-none !border-none w-full",
          headerTitle: "!text-white text-xl",
          headerSubtitle: "!text-slate-400",
          socialButtonsBlockButton:
            "!bg-slate-800/80 !border-slate-600/50 !text-white hover:!bg-slate-700 transition-all",
          socialButtonsBlockButtonText: "!text-white !font-medium",
          formFieldLabel: "!text-slate-300 !font-medium",
          formFieldInput:
            "!bg-slate-800/80 !border-slate-600/50 !text-white !placeholder-slate-500 focus:!border-sky-500 focus:!ring-1 focus:!ring-sky-500/50",
          footerActionLink: "!text-sky-400 hover:!text-sky-300",
          formButtonPrimary:
            "!bg-gradient-to-r !from-sky-500 !to-cyan-400 !text-white !font-semibold !shadow-lg !shadow-sky-500/20 hover:!brightness-110 !transition-all",
          dividerLine: "!bg-slate-700",
          dividerText: "!text-slate-500",
          footer: "!hidden",
          internal: "!hidden",
        },
      }}
    >
      <html lang="en">
        <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
