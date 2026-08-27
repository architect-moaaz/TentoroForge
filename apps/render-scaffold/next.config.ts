import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The scaffold renders LLM-generated schemas — generated code may have
  // type errors that shouldn't block screenshot capture. Ignoring build
  // errors here is intentional, not a workaround for our own type issues.
  typescript: { ignoreBuildErrors: true },
  // On UAT the caddy edge routes only `/p/*` to this container — everything
  // else falls to the platform frontend. `basePath` scopes every route AND
  // every asset URL under `/p`, so `/_next/static/...` becomes
  // `/p/_next/static/...` uniformly (App Router's `assetPrefix` misses some
  // <head> tags in Next 15, but `basePath` covers them all). The page routes
  // live at `src/app/[projectId]/[...slug]/page.tsx` — basePath prepends the
  // `/p`, giving the final URL `/p/{projectId}/{slug}`. Env-gated so local
  // dev (`next dev -p 6503`, no reverse proxy) stays at the root.
  basePath: process.env.NEXT_BASE_PATH || undefined,
  transpilePackages: [
    "@tentoroforge/engine",
    "@tentoroforge/renderer",
    "@tentoroforge/library",
    "@tentoroforge/schema",
  ],
  // isomorphic-dompurify (used by the renderer's dispatch layer) bundles
  // jsdom which reads browser/default-stylesheet.css relative to the
  // compiled chunk directory — a path that doesn't exist when webpack
  // inlines the module. Marking it as a server external lets Next.js
  // require() it natively from node_modules where the file path resolves.
  serverExternalPackages: ["isomorphic-dompurify"],
};

export default nextConfig;
