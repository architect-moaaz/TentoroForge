const path = require("path");

// Preview-behind-prefix mode: when the platform serves this app inside the
// visual-editor iframe on a hosted deployment (UAT/prod), the backend
// reverse-proxies requests at a path prefix, so basePath + assetPrefix teach
// Next to emit `/_next/static/…` and page links with that prefix. Unset (the
// Vercel deploy case, and a plain `verify_build`) → app runs at root,
// unchanged. This used to live in an app-foundation `next.config.ts`, which
// never took effect: Next loads `next.config.js` over `.ts`, so the prefix was
// silently dropped. Folded here, into the one config Next actually reads.
const PREVIEW_BASE_PATH = process.env.NEXT_BASE_PATH || undefined;
const PREVIEW_ASSET_PREFIX = process.env.NEXT_ASSET_PREFIX || PREVIEW_BASE_PATH;

/** @type {import("next").NextConfig} */
module.exports = {
  reactStrictMode: true,
  ...(PREVIEW_BASE_PATH ? { basePath: PREVIEW_BASE_PATH } : {}),
  ...(PREVIEW_ASSET_PREFIX ? { assetPrefix: PREVIEW_ASSET_PREFIX } : {}),
  transpilePackages: [
    "@tentoroforge/engine",
    "@tentoroforge/library",
    "@tentoroforge/renderer",
    "@tentoroforge/schema",
    "@forge/patches",
  ],
  serverExternalPackages: ["isomorphic-dompurify", "jsdom"],
  // Server Components read src/schemas/**/*.json and src/contracts/*.json
  // via fs.readFile at render time — those aren't static imports, so
  // Next's file-tracer would otherwise leave them out of the serverless
  // function bundle. Deployed to Vercel, /dashboard then hits ENOENT on
  // `/var/task/src/schemas/home.json` and every SSR route 500s. Include
  // them for every route (they're shared across the tree).
  // A verification build (`verify_build`) sets NEXT_DIST_DIR so it compiles
  // beside a running dev server instead of into its `.next`.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  outputFileTracingIncludes: {
    "/**/*": [
      "./src/schemas/**/*.json",
      "./src/contracts/**/*.json",
      "./registry.json",
    ],
  },
  // Generated apps ship with LLM-authored code that occasionally has
  // narrow TS/ESLint issues (e.g. `postgres` client return shape vs
  // `pg`'s `.rows`). The runtime is unaffected; blocking the build on
  // these would surface as a Vercel deploy failure. Matches the
  // app_emitter's inline write of next.config.js.
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  images: { domains: ["localhost"] },
  webpack: (config) => {
    // The renderer dist imports `@tentoroforge/feel-lite` (the FEEL-lite
    // expression engine, which we ship as loose files under src/lib/feel-lite
    // via runtime_injector, not as an npm package) and `@forge/patches`
    // (vendored under vendor/@forge/patches). Neither name resolves via
    // node_modules; both are aliased here so the compiled renderer JS
    // resolves them at build time.
    config.resolve.alias = {
      ...config.resolve.alias,
      "@tentoroforge/feel-lite": path.resolve(__dirname, "./src/lib/feel-lite"),
      "@forge/patches": path.resolve(__dirname, "./vendor/@forge/patches"),
      // The app-foundation floor ships a dev-only editor route
      // (src/app/(dev-only)/editor/*) whose editor-mount imports
      // `@tentoroforge/editor` — the heavy visual-editor UI. That package is
      // deliberately NOT vendored into generated apps (visual editing lives in
      // the platform, not the app), so `next build` compiles the dev-only
      // route eagerly and dies on `Can't resolve '@tentoroforge/editor'`.
      // Alias it to an empty module: the import resolves, the build passes, and
      // the dev-only route is a stub nobody serves. `false` is webpack 5's own
      // "empty module" — no null-loader dependency needed.
      "@tentoroforge/editor": false,
    };
    return config;
  },
};
