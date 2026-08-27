// ── Sprite Image Loader & Cache ─────────────────────────────────────────────

import type { SpriteManifest } from "./types";

const BASE_PATH = "/sprites/";
const cache = new Map<string, HTMLImageElement>();

/**
 * Fetch the sprite manifest from /sprites/manifest.json.
 */
export async function loadManifest(): Promise<SpriteManifest> {
  const res = await fetch(`${BASE_PATH}manifest.json`);
  if (!res.ok) {
    throw new Error(`Failed to load sprite manifest: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<SpriteManifest>;
}

/**
 * Load a single sprite image by relative path (under /sprites/).
 * Returns a cached image if already loaded.
 */
export function loadSprite(path: string): Promise<HTMLImageElement> {
  const fullPath = path.startsWith("/") ? path : `${BASE_PATH}${path}`;

  const existing = cache.get(fullPath);
  if (existing) return Promise.resolve(existing);

  return new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      cache.set(fullPath, img);
      resolve(img);
    };
    img.onerror = () => reject(new Error(`Failed to load sprite: ${fullPath}`));
    img.src = fullPath;
  });
}

/**
 * Preload every sprite referenced in the manifest.
 */
export async function preloadAll(manifest: SpriteManifest): Promise<void> {
  const toLoad: { path: string; aliases: string[] }[] = [];

  const categories: (keyof SpriteManifest)[] = [
    "tiles",
    "furniture",
    "characters",
    "characters_idle",
    "characters_working",
    "characters_walk",
    "effects",
  ];

  for (const cat of categories) {
    const entries = manifest[cat];
    if (entries) {
      for (const [key, path] of Object.entries(entries)) {
        // Register under logical key like "characters_idle_planner"
        const logicalKey = `${cat}_${key}`;
        toLoad.push({ path, aliases: [logicalKey, key] });
      }
    }
  }

  // Deduplicate by path
  const seen = new Set<string>();
  const unique = toLoad.filter((item) => {
    if (seen.has(item.path)) return false;
    seen.add(item.path);
    return true;
  });

  await Promise.all(
    unique.map(async ({ path, aliases }) => {
      const img = await loadSprite(path);
      // Also register under all alias keys so getSprite("characters_idle_planner") works
      for (const alias of aliases) {
        cache.set(alias, img);
      }
    }),
  );
}

/**
 * Get a previously loaded sprite from the cache.
 * The key can be either the manifest key (resolved via BASE_PATH) or the full path.
 */
export function getSprite(key: string): HTMLImageElement | null {
  // Try direct lookup first
  const direct = cache.get(key);
  if (direct) return direct;

  // Try with base path prepended
  const withBase = `${BASE_PATH}${key}`;
  return cache.get(withBase) ?? null;
}
