"""Extract a brand color palette from a logo image.

Uses k-means clustering on the logo's non-transparent pixels to find
dominant colors, filters out near-neutrals (very light grays, blacks
that are likely background or stroke), and returns the most-saturated
cluster as the primary brand color.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans


@dataclass(frozen=True)
class BrandPalette:
    """Result of brand extraction from a logo."""
    primary_rgb: tuple[int, int, int]
    primary_hex: str
    secondary_rgb: tuple[int, int, int] | None
    secondary_hex: str | None
    raw_clusters: list[tuple[int, int, int]]  # all k clusters, for debugging


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _is_near_neutral(rgb: tuple[int, int, int]) -> bool:
    """A color is neutral when its channels are all within 15 of each other,
    OR when its average is very high (>240, near-white) or very low (<25, near-black)."""
    r, g, b = rgb
    spread = max(r, g, b) - min(r, g, b)
    avg = (r + g + b) / 3
    return spread < 15 or avg > 240 or avg < 25


def _saturation(rgb: tuple[int, int, int]) -> float:
    """Rough saturation: max channel minus min channel, normalised to [0, 1]."""
    r, g, b = rgb
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


def extract_palette_from_logo(logo_bytes: bytes, k: int = 5) -> BrandPalette:
    """Extract a BrandPalette from a logo's bytes (PNG/JPG).

    Algorithm:
      1. Decode + downsample to 64×64 for speed
      2. Drop fully-transparent pixels (alpha < 16)
      3. K-means with k clusters on RGB values
      4. Filter out near-neutral clusters
      5. Pick most-saturated as primary, second-most as secondary
    """
    img = Image.open(BytesIO(logo_bytes))
    img.thumbnail((64, 64))  # downsample
    img = img.convert("RGBA")
    pixels = np.array(img).reshape(-1, 4)
    # Drop transparent pixels
    pixels = pixels[pixels[:, 3] >= 16][:, :3]
    if len(pixels) < k:
        # Not enough non-transparent pixels — fall back to average colour
        avg = tuple(int(c) for c in pixels.mean(axis=0))
        return BrandPalette(
            primary_rgb=avg,
            primary_hex=_rgb_to_hex(avg),
            secondary_rgb=None,
            secondary_hex=None,
            raw_clusters=[avg],
        )
    # K-means
    actual_k = min(k, len(pixels))
    km = KMeans(n_clusters=actual_k, n_init=10, random_state=42)
    km.fit(pixels)
    clusters: list[tuple[int, int, int]] = [
        tuple(int(c) for c in centre) for centre in km.cluster_centers_
    ]
    # Filter neutrals
    saturated = [c for c in clusters if not _is_near_neutral(c)]
    # Sort by saturation, descending
    saturated.sort(key=_saturation, reverse=True)
    if not saturated:
        # All clusters were neutral — pick the most-saturated even if it's drab
        clusters.sort(key=_saturation, reverse=True)
        primary = clusters[0]
        secondary = clusters[1] if len(clusters) > 1 else None
    else:
        primary = saturated[0]
        secondary = saturated[1] if len(saturated) > 1 else None
    return BrandPalette(
        primary_rgb=primary,
        primary_hex=_rgb_to_hex(primary),
        secondary_rgb=secondary,
        secondary_hex=_rgb_to_hex(secondary) if secondary else None,
        raw_clusters=clusters,
    )
