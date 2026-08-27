/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  transpilePackages: ["@tentoroforge/engine", "@tentoroforge/library", "@tentoroforge/renderer", "@tentoroforge/schema"],
  serverExternalPackages: ["isomorphic-dompurify", "jsdom"],
  outputFileTracingIncludes: {
    "/**/*": ["./src/schemas/**/*.json", "./src/contracts/**/*.json", "./registry.json"],
  },
  typescript: { ignoreBuildErrors: true },
  images: { domains: ["localhost"] },
};
