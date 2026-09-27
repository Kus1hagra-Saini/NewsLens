import { useState } from "react";

import { cn } from "@/lib/cn";

/**
 * Editorial image frame — single reusable component for every article
 * image in NewsLens.
 *
 * Design commitments:
 *
 *   - Lazy loaded (``loading="lazy"``, ``decoding="async"``) so an
 *     off-screen image never blocks the first paint.
 *   - Graceful failure — a broken URL is caught, the frame renders
 *     ``null`` and never shows a broken-image glyph or placeholder.
 *   - Muted background while the image resolves, no spinner. The
 *     surrounding editorial layout carries the visual weight; the
 *     image should appear rather than announce itself loading.
 *   - Optional caption / credit line beneath in the outlet's own
 *     small caps, matching the rest of the site's typography.
 *   - Size is fixed via CSS so layout never jumps when the image
 *     finally decodes.
 *
 * The image URL itself lives on the outlet's CDN — NewsLens never
 * downloads or rehosts. If the outlet takes the URL down or the
 * user's network can't reach it, ``onError`` fires and we render
 * nothing at all. This is deliberate: silent absence beats a broken
 * placeholder in an editorial layout.
 */

export type ImageAspect = "wide" | "square" | "auto";

/**
 * Height preset for the frame.
 *
 * ``"hero"``       — restrained editorial hero: ~280px on phones,
 *                    grows to ~440px on desktop. Never dominates the
 *                    analytical content that follows.
 * ``"supporting"`` — a shorter frame used mid-page between analytical
 *                    sections. ~220px mobile, ~360px desktop.
 * ``"card"``       — small cover for Home cards, using an aspect ratio
 *                    so the tile scales with the column width.
 *
 * When ``size`` is provided it takes precedence over ``aspect``.
 */
export type ImageSize = "hero" | "supporting" | "card";

export function ImageFrame({
  url,
  alt,
  caption,
  aspect = "wide",
  size,
  priority = false,
  className,
  imgClassName,
}: {
  url: string;
  /** Alt text — outlet name + short context is the usual pattern. */
  alt: string;
  /** Optional small caps line under the image (e.g. "Photo · NDTV"). */
  caption?: string;
  /**
   * Used only when ``size`` is not provided (Home cards keep an
   * aspect-ratio look). When ``size`` is set, the frame uses a
   * responsive fixed height instead so hero + supporting images stay
   * editorially restrained on wide screens.
   */
  aspect?: ImageAspect;
  size?: ImageSize;
  /**
   * ``true`` for the hero image above the fold — sets
   * ``loading="eager"`` and ``fetchpriority="high"`` so it isn't
   * demoted by the lazy-loading defaults. Every other frame stays
   * lazy.
   */
  priority?: boolean;
  className?: string;
  imgClassName?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;

  // Size-based layout takes priority over aspect. Responsive fixed
  // heights keep the hero + supporting images editorially restrained
  // on wide screens; on mobile they drop to comfortable phone-friendly
  // heights. Width fills the column; ``object-cover`` keeps the crop
  // clean regardless of the source's native aspect ratio.
  const sizeCls =
    size === "hero"
      ? "h-[280px] sm:h-[360px] md:h-[400px] lg:h-[440px]"
    : size === "supporting"
      ? "h-[220px] sm:h-[280px] md:h-[320px] lg:h-[360px]"
    : "";

  const aspectCls =
    size ? ""
    : aspect === "wide"   ? "aspect-[16/9]"
    : aspect === "square" ? "aspect-square"
    : "";

  return (
    <figure className={cn("min-w-0", className)}>
      <div
        className={cn(
          "relative w-full overflow-hidden bg-surface-inset",
          sizeCls,
          aspectCls,
        )}
      >
        <img
          src={url}
          alt={alt}
          loading={priority ? "eager" : "lazy"}
          // fetchpriority isn't in every React DOM typing yet — cast
          // through unknown to appease TS while keeping the browser
          // hint intact for the hero image.
          {...({ fetchpriority: priority ? "high" : "auto" } as unknown as { fetchpriority: string })}
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className={cn(
            "h-full w-full object-cover object-center",
            "transition-opacity duration-500 ease-editorial",
            imgClassName,
          )}
        />
      </div>
      {caption ? (
        <figcaption className="mt-3 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}
