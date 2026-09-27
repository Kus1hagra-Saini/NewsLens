import { cn } from "@/lib/cn";
import type { StoryImage } from "@/api/types";

import { ImageFrame } from "./ImageFrame";

/**
 * Story-page image treatments.
 *
 * The backend has already applied the count rule (2–6 → 1, 7–10 → 2,
 * 11+ → 3), outlet-diversity and de-duplication server-side, so the
 * frontend just decides HOW to render the N images it was given.
 *
 * Two components:
 *
 *   <StoryHeroImage />       — a single hero placed above the story
 *                              header. Rendered at the restrained
 *                              "hero" height so it never dominates the
 *                              analytical content that follows.
 *
 *   <StorySupportingImage />  — a single supporting image, dropped
 *                              INTO the middle of the section stack
 *                              between analytical sections. The page
 *                              composes several of these interleaved
 *                              with sections rather than stacking all
 *                              supporting images together.
 *
 * Neither component renders anything when there is no image to show
 * — the caller doesn't need to gate the section itself.
 */

// ---------------------------------------------------------------------------
// Hero
// ---------------------------------------------------------------------------

export function StoryHeroImage({
  image,
  className,
}: {
  image: StoryImage | null;
  className?: string;
}) {
  if (!image) return null;
  return (
    <ImageFrame
      url={image.url}
      alt={`Photo from ${image.outlet_name}`}
      caption={`Photo · ${image.outlet_name}`}
      size="hero"
      priority
      className={cn(className)}
    />
  );
}

// ---------------------------------------------------------------------------
// Supporting image — one at a time, slotted between analytical sections
// ---------------------------------------------------------------------------

export function StorySupportingImage({
  image,
  className,
}: {
  image: StoryImage | null;
  className?: string;
}) {
  if (!image) return null;
  return (
    <div className={cn("reveal-up mx-auto max-w-3xl", className)}>
      <ImageFrame
        url={image.url}
        alt={`Photo from ${image.outlet_name}`}
        caption={`Photo · ${image.outlet_name}`}
        size="supporting"
      />
    </div>
  );
}
