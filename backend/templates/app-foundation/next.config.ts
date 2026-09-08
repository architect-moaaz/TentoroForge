import type { NextConfig } from "next";

// Production exclusion strategy: `null-loader` webpack rule.
// Any module whose resolved file path contains `/(dev-only)/` is replaced with an
// empty module at build time when NODE_ENV=production.  This means the editor
// routes, save/load/suggest API routes, and all their imports are fully
// tree-shaken from the production bundle.
//
// null-loader (v4) is a standard webpack loader for this pattern — it simply
// emits an empty module.  The alternative (Next.js `experimental.outputFileTracingExcludes`)
// only controls file-system tracing, not bundling, so the webpack approach is
// the correct one for route-level exclusion.
// Preview-behind-prefix mode: when the platform runs the app inside the
// visual editor iframe on a hosted deployment (UAT/prod), the backend
// reverse-proxies requests at /api/projects/<id>/preview/serve/... so the
// browser never needs a direct route to the internal Next dev server.
// Setting basePath + assetPrefix teaches Next to emit all asset URLs and
// page links with the prefix so /_next/static/... and page navigation both
// route back through the same proxy.
// Unset (the Vercel deploy case) → app runs at root, unchanged behavior.
const PREVIEW_BASE_PATH = process.env.NEXT_BASE_PATH || undefined;
const PREVIEW_ASSET_PREFIX = process.env.NEXT_ASSET_PREFIX || PREVIEW_BASE_PATH;

const nextConfig: NextConfig = {
  ...(PREVIEW_BASE_PATH ? { basePath: PREVIEW_BASE_PATH } : {}),
  ...(PREVIEW_ASSET_PREFIX ? { assetPrefix: PREVIEW_ASSET_PREFIX } : {}),
  // Ensure runtime-read JSON travels with the serverless function bundle.
  // Server Components read src/schemas/**/*.json and src/contracts/*.json via
  // fs.readFile at render time — those reads aren't static imports, so
  // Next.js's file-tracer would otherwise leave them out and the deployed
  // function hits ENOENT on `/var/task/src/schemas/…`. Include them for every
  // route (the schemas are shared across the tree).
  // A verification build (`verify_build`) sets NEXT_DIST_DIR so it compiles
  // beside a running dev server instead of into its `.next`.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // ONE object, every runtime-read file. These lists lived in TWO
  // `outputFileTracingIncludes` keys in this same literal, and the second
  // silently overwrote the first (duplicate object key — last wins), so the
  // schemas / contracts / registry.json entries were dropped from the
  // serverless bundle and hit ENOENT at render on Vercel, the very failure the
  // first block existed to prevent. All of them are fs-read at request time
  // (Server Components read src/schemas/**/*.json + src/contracts/*.json;
  // rules/engine.ts loadRules reads rules/**), none is a static import Next's
  // file-tracer can see, so each has to be forced into every function's trace.
  outputFileTracingIncludes: {
    "/**": [
      "./src/schemas/**/*.json",
      "./src/contracts/**/*.json",
      "./registry.json",
      "./rules/**/*",
      "./src/rules/**/*",
    ],
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  images: {
    domains: ["localhost", "picsum.photos", "placehold.co"],
  },
  webpack(config, { isServer: _isServer }) {
    if (process.env.NODE_ENV === "production") {
      // Exclude all files inside any `(dev-only)` route group from prod builds.
      // The regex matches the directory separator on both Unix and Windows.
      config.module.rules.push({
        test: /[\\/]\(dev-only\)[\\/]/,
        use: "null-loader",
      });
    }
    return config;
  },
};

export default nextConfig;
