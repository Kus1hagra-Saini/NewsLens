import type { StoryDetail as StoryDetailPayload } from "@/api/types";

import { SectionKicker } from "./primitives";

/**
 * FEATURE 2 — Story Summary ("The Story in One Minute")
 *
 * Presents ``stories.summary`` — the existing factual story summary
 * written by the clustering pipeline. This is intentionally kept
 * separate from the LLM-generated comparison analysis, which is
 * rendered by <WhatDiffers /> below. The two answer different
 * questions:
 *
 *   - <StorySummary /> answers "What happened?" (factual)
 *   - <WhatDiffers />  answers "How does the coverage differ?" (analytic)
 *
 * The section deliberately looks like a long-form editorial lede
 * rather than a dashboard card: a wide serif column, generous
 * leading, and a small kicker line that names the section.
 */
export function StorySummary({ story }: { story: StoryDetailPayload }) {
  const summary = (story.summary ?? "").trim();

  // If the clustering pipeline has produced no summary yet we hide the
  // section entirely rather than showing an "empty state" — the page
  // should not feel like a report with missing tiles.
  if (!summary) return null;

  return (
    <section aria-labelledby="story-summary-heading" className="reveal-up">
      <div className="max-w-[68ch]">
        <div id="story-summary-heading">
          <SectionKicker>The story in one minute</SectionKicker>
        </div>
        <div className="mt-4 space-y-4 font-display text-[19px] leading-[1.6] text-ink-primary sm:text-[22px] sm:leading-[1.55]">
          {splitParagraphs(summary).map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
        <p className="mt-4 text-[11.5px] uppercase tracking-[0.14em] text-ink-muted">
          Summary from NewsLens clustering, not from any single outlet.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// WhatDiffers — the comparative analysis text
// ---------------------------------------------------------------------------

/**
 * Renders ``story_comparisons.differences`` — the comparative-analysis
 * paragraph. Explicitly labelled as analysis of coverage differences so
 * a reader never mistakes it for a factual recap.
 *
 * When Compare hasn't run for this story (or produced empty prose) the
 * whole section is hidden — no placeholder card.
 */
export function WhatDiffers({ story }: { story: StoryDetailPayload }) {
  const text = (story.comparison?.differences ?? "").trim();
  if (!text) return null;

  const paragraphs = splitParagraphs(text);

  return (
    <section aria-labelledby="what-differs-heading" className="reveal-up">
      <div className="max-w-[68ch]">
        <div id="what-differs-heading">
          <SectionKicker>What differs across coverage</SectionKicker>
        </div>
        <h3 className="mt-2 font-display text-[24px] leading-[1.2] tracking-[-0.01em] text-ink-primary sm:text-[28px]">
          Where the outlets diverge
        </h3>
        <p className="mt-2 text-[13.5px] leading-relaxed text-ink-secondary">
          A synthesis of how outlets are framing and prioritising this story,
          derived from the article-level analysis below.
        </p>
        <div className="mt-6 space-y-4 text-[16px] leading-[1.7] text-ink-secondary sm:text-[17px]">
          {paragraphs.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------

function splitParagraphs(text: string): string[] {
  return text
    .split(/\n\n+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}
