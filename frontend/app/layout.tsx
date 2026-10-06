import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import type { ReactNode } from "react";
import { runtimeConfigScript, serverRuntimeConfig } from "@/lib/runtime-config";
import { Providers } from "./providers";
import "./globals.css";

const body = Geist({ subsets: ["latin"], variable: "--font-body" });
const code = Geist_Mono({ subsets: ["latin"], variable: "--font-code" });

export const metadata: Metadata = {
  title: "HootPR | AI code reviews for GitHub and GitLab",
  description: "AI pull request reviews with static analysis, agents and a judge model.",
};

// API_PUBLIC_URL is read per request (not baked into the build), so render dynamically.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: runtimeConfigScript(serverRuntimeConfig()) }} />
      </head>
      <body
        className={`${body.variable} ${code.variable} flex min-h-screen flex-col bg-background font-sans antialiased`}
      >
        <Providers>
          {children}
        </Providers>
      </body>
    </html>
  );
}
