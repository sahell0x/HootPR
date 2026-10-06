import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Keep server.js at .next/standalone/server.js (no parent lockfiles/workspace inference).
  outputFileTracingRoot: path.join(__dirname),
  poweredByHeader: false,
  // No /api rewrite: the browser calls the API origin directly (API_PUBLIC_URL, see lib/runtime-config.ts).
};

export default nextConfig;
