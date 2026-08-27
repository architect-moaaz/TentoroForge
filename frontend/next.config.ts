import type { NextConfig } from "next";

const FASTAPI_URL = process.env.FASTAPI_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

const nextConfig: NextConfig = {
  // Produce a self-contained server bundle in .next/standalone so the
  // production Docker image can copy just that + .next/static + public/
  // and run `node server.js` — no node_modules needed at runtime.
  output: "standalone",
  // TS errors don't gate the deploy — same posture as the generated
  // apps. Prod builds still work; the platform's Python API is the
  // source of truth for correctness. Type errors surface locally.
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  // Keep isomorphic-dompurify (which pulls jsdom) out of the SSR bundle so
  // jsdom doesn't try to resolve a default-stylesheet.css path that doesn't
  // exist in Next.js's build dir. The renderer only uses DOMPurify for the
  // "Custom" node escape-hatch; that path hydrates client-side anyway.
  serverExternalPackages: ["isomorphic-dompurify", "jsdom"],
  // Ensure local workspace ESM packages are transpiled by Next.js webpack.
  transpilePackages: ["@forge/registry", "@forge/patches"],
  async rewrites() {
    // Forward /api/projects/* to FastAPI. The schema editor uses relative
    // /api/projects/<id>/... URLs; this rewrite keeps the editor's apiBaseUrl
    // simple and avoids per-request token plumbing on the client.
    return [
      {
        source: "/api/projects/:path*",
        destination: `${FASTAPI_URL}/api/projects/:path*`,
      },
    ];
  },
};

export default nextConfig;
