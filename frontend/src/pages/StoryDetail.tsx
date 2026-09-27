import { useMemo } from "react";
import { useParams } from "react-router-dom";

import { DisclaimerFootnote } from "@/components/dashboard/DisclaimerFootnote";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { Skeleton } from "@/components/ui/Skeleton";
import { ArticlesByOutlet } from "@/components/story-detail/ArticlesByOutlet";
import { CoverageGaps } from "@/components/story-detail/CoverageGaps";
import { FramingSection } from "@/components/story-detail/FramingSection";
import { MediaBiasDistribution } from "@/components/story-detail/MediaBiasDistribution";
import { OutletEmphasis } from "@/components/story-detail/OutletEmphasis";
import { SourceVoicesSection } from "@/components/story-detail/SourceVoices";
import { StoryHeader } from "@/components/story-detail/StoryHeader";
import {
  StoryHeroImage,
  StorySupportingImage,
} from "@/components/story-detail/StoryImages";
import {
  StorySummary,
  WhatDiffers,
} from "@/components/story-detail/StorySummary";
import {
  BackLink,
  SectionRule,
} from "@/components/story-detail/primitives";
import {
  aggregateFramingByOutlet,
  aggregateSourceDistribution,
  collectQuotedSources,
  coverageGapsFromMatrix,
  groupArticlesByOutlet,
  outletsEmphasisFromMatrix,
} from "@/components/story-detail/helpers";
import { useStoryDetail } from "@/api/queries";
import type {
  StoryDetail as StoryDetailPayload,
  StoryImage,
} from "@/api/types";

/**
 * /stories/:id — the flagship NewsLens analytical experience.
 *
 * This page answers, top to bottom, one editorial question:
 *
 *   "What is happening in this story, and how differently are
 *   different outlets covering it?"
 *
 * Section order:
 *
 *   1. StoryHeader
 *   2. StorySummary               (factual "story in one minute")
 *   3. MediaBiasDistribution      (publication-level, external ratings)
 *   4. WhatDiffers                (the analytic counterpart to summary)
 *   5. OutletEmphasis
 *   6. FramingSection             (article-level framing — NOT political bias)
 *   7. SourceVoicesSection        (who is being heard?)
 *   8. CoverageGaps
 *   9. ArticlesByOutlet           (full coverage)
 *
 * Note: the older "How each outlet titled it" (HeadlineComparison)
 * section was removed because the actual article headlines already
 * appear verbatim inside ArticlesByOutlet — the section was pure
 * duplication of what Full Coverage already shows.
 *
 * MediaBiasDistribution and FramingSection are DIFFERENT concepts:
 *   - Bias distribution is publication-level and comes from external
 *     third-party ratings (currently MBFC).
 *   - Framing is article-level (critical / neutral / supportive) and
 *     comes from our LLM analysis of each article's text.
 * The two are rendered in distinct sections and use distinct
 * vocabularies so a reader never conflates them.
 *
 * Image placement:
 *   - Hero image (when present) sits above the header, sized so it
 *     accompanies rather than dominates the story.
 *   - Supporting images (1 or 2 per the server-side count rule) are
 *     INTERLEAVED between analytical sections rather than stacked
 *     together, so the page always reads as content-first with
 *     images that give visual context.
 *
 * Section components hide themselves internally when they lack data —
 * the page never renders empty placeholders. The shell mirrors those
 * visibility rules so it only inserts a section rule between sections
 * that actually rendered.
 */
export default function StoryDetailPage() {
  const params = useParams<{ id?: string }>();
  const idNum = params.id ? Number(params.id) : NaN;
  const isValidId = Number.isFinite(idNum) && idNum > 0;

  const query = useStoryDetail(isValidId ? idNum : null);

  if (!isValidId) {
    return (
      <div className="flex flex-col">
        <BackLink />
        <div className="mt-14">
          <ErrorState
            title="Invalid story id"
            error={
              new Error(`"${params.id}" is not a valid numeric story id.`)
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <BackLink />

      {query.isLoading ? (
        <StoryDetailSkeleton />
      ) : query.isError ? (
        <div className="mt-14">
          <ErrorState
            title="Couldn't load story"
            error={query.error}
            onRetry={() => query.refetch()}
          />
        </div>
      ) : !query.data ? (
        <div className="mt-14">
          <EmptyState
            title="Story not found"
            message="It may have been removed."
          />
        </div>
      ) : (
        <StoryBody story={query.data} />
      )}

      <DisclaimerFootnote />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Body composition — every section stands on its own; the shell
// arranges them, inserts the section rule between visible sections,
// and drops supporting images into the middle of the stack.
// ---------------------------------------------------------------------------

function StoryBody({ story }: { story: StoryDetailPayload }) {
  const articles = story.articles ?? [];

  // Visibility predicates. These mirror the internal `return null`
  // conditions inside each section component so the shell can decide
  // which section rules to draw. Kept in one memoised block so a
  // large story doesn't recompute the derivations on every render.
  const visibility = useMemo(() => {
    const framingRows = aggregateFramingByOutlet(articles);
    const emphasisRows = outletsEmphasisFromMatrix(
      story.comparison?.coverage_matrix ?? null,
      articles,
    );
    const gapsRows = coverageGapsFromMatrix(
      story.comparison?.not_present_here ?? null,
      articles,
    );
    const sourceRows = aggregateSourceDistribution(articles);
    const sourceTotals = sourceRows.reduce((s, r) => s + r.total, 0);
    const quoteCount = collectQuotedSources(articles).length;
    const outletGroups = groupArticlesByOutlet(articles);

    // The bias distribution is visible whenever the backend attached
    // ANY payload — the component itself renders either the bar (when
    // eligible) or a short "not enough rated coverage" note (when not),
    // so the shell only needs to check that the payload exists.
    return {
      summary: Boolean((story.summary ?? "").trim()),
      bias: story.bias_distribution !== null && story.bias_distribution !== undefined,
      differs: Boolean((story.comparison?.differences ?? "").trim()),
      emphasis: emphasisRows.length > 0,
      framing: framingRows.length > 0,
      sources: sourceTotals > 0 || quoteCount > 0,
      gaps: gapsRows.some((r) => r.items.length > 0),
      full: outletGroups.length > 0,
    };
  }, [articles, story.comparison, story.summary, story.bias_distribution]);

  // Hero + supporting images. The server already applied the count
  // rule (2–6 → max 1, 7–10 → max 2, 11+ → max 3), so ``story_images``
  // is already the right length. The hero is the first entry; the
  // rest get slotted BETWEEN sections below so multiple images are
  // never stacked together with no meaningful content in between.
  const storyImages: StoryImage[] = story.story_images ?? [];
  const heroImage = storyImages[0] ?? null;
  const supportingImages = storyImages.slice(1);
  // Insertion targets for supporting images, in order:
  //   1st goes AFTER the "framing" section (rough middle of the stack)
  //   2nd goes AFTER "sources" so the last third of the page has one too
  // Any extras (there should be none — the API caps at 3) drop off.
  const SUPPORTING_SLOTS = ["framing", "sources"] as const;

  // Build the section list. Each entry is one editorial section OR a
  // supporting-image slot, so the map below can thread section rules
  // and images through the same loop.
  interface SectionEntry {
    key: string;
    kind: "section" | "image";
    visible: boolean;
    node: React.ReactNode;
  }

  const sections: SectionEntry[] = [];
  const push = (e: SectionEntry) => sections.push(e);

  push({
    key: "summary",
    kind: "section",
    visible: visibility.summary,
    node: <StorySummary story={story} />,
  });
  push({
    key: "bias",
    kind: "section",
    visible: visibility.bias,
    node: <MediaBiasDistribution distribution={story.bias_distribution} />,
  });
  push({
    key: "differs",
    kind: "section",
    visible: visibility.differs,
    node: <WhatDiffers story={story} />,
  });
  push({
    key: "emphasis",
    kind: "section",
    visible: visibility.emphasis,
    node: <OutletEmphasis comparison={story.comparison} articles={articles} />,
  });
  push({
    key: "framing",
    kind: "section",
    visible: visibility.framing,
    node: <FramingSection story={story} articles={articles} />,
  });

  // Slot 1 — after framing, before sources.
  if (supportingImages[0]) {
    push({
      key: "img-1",
      kind: "image",
      visible: true,
      node: <StorySupportingImage image={supportingImages[0]} />,
    });
  }

  push({
    key: "sources",
    kind: "section",
    visible: visibility.sources,
    node: <SourceVoicesSection articles={articles} />,
  });

  // Slot 2 — after sources, before gaps + full coverage.
  if (supportingImages[1]) {
    push({
      key: "img-2",
      kind: "image",
      visible: true,
      node: <StorySupportingImage image={supportingImages[1]} />,
    });
  }

  push({
    key: "gaps",
    kind: "section",
    visible: visibility.gaps,
    node: <CoverageGaps comparison={story.comparison} articles={articles} />,
  });
  push({
    key: "full",
    kind: "section",
    visible: visibility.full,
    node: <ArticlesByOutlet articles={articles} />,
  });

  const visibleEntries = sections.filter((s) => s.visible);
  // Guard against a supporting-image slot ending up as the very first
  // or very last entry (would sit alone with no analytical content
  // around it). If that happens, drop the orphan image slot.
  const trimmed = trimOrphanImages(
    visibleEntries,
    SUPPORTING_SLOTS as unknown as string[],
  );

  return (
    <article className="flex flex-col">
      {/* Hero image — restrained editorial height, comfortable
          separation from the header below. */}
      <StoryHeroImage image={heroImage} className={heroImage ? "mb-10 md:mb-14" : ""} />
      <StoryHeader story={story} />

      {trimmed.length > 0 ? (
        <div className="mt-14 md:mt-20">
          {trimmed.map((entry, i) => {
            // Rules go between two adjacent SECTIONS. We suppress the
            // rule immediately before an image slot and immediately
            // before the first section after an image, so images sit
            // in comfortable whitespace rather than being sliced by
            // hairlines above and below.
            const prev = trimmed[i - 1];
            const showRule =
              i > 0 &&
              prev?.kind !== "image" &&
              entry.kind !== "image";
            return (
              <div key={entry.key}>
                {showRule ? <SectionRule /> : null}
                {entry.kind === "image" ? (
                  <div className="my-16 md:my-20">{entry.node}</div>
                ) : (
                  entry.node
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mt-14">
          <EmptyState
            title="Analysis in progress"
            message="NewsLens hasn't produced any analytical output for this story yet. Check back once enrichment and comparison have completed."
          />
        </div>
      )}
    </article>
  );
}

// A supporting image at the top or bottom of the visible list would
// sit next to the header or the footer with no analysis around it.
// Drop it if that happens — never render an orphan image.
function trimOrphanImages<T extends { kind: "section" | "image" }>(
  entries: T[],
  _imageKeys: string[],
): T[] {
  const out = [...entries];
  while (out.length && out[0].kind === "image") out.shift();
  while (out.length && out[out.length - 1].kind === "image") out.pop();
  return out;
}

// ---------------------------------------------------------------------------
// Loading skeleton — mirrors the header shape so the layout doesn't
// jump when data arrives.
// ---------------------------------------------------------------------------

function StoryDetailSkeleton() {
  return (
    <div className="reveal-up">
      <div className="border-t-2 border-ink-primary pt-3">
        <Skeleton className="h-3 w-64" />
      </div>
      <Skeleton className="mt-8 h-14 w-full max-w-4xl" />
      <Skeleton className="mt-3 h-14 w-3/4" />
      <div className="mt-10 flex flex-wrap gap-8 border-b border-ink-primary/10 pb-8">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="min-w-[120px]">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-2 h-6 w-24" />
          </div>
        ))}
      </div>

      {/* Summary block */}
      <div className="mt-16">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="mt-4 h-5 w-full max-w-2xl" />
        <Skeleton className="mt-2 h-5 w-5/6 max-w-2xl" />
        <Skeleton className="mt-2 h-5 w-4/6 max-w-2xl" />
      </div>

      {/* Section placeholders */}
      <Skeleton className="mt-16 h-3 w-40" />
      <Skeleton className="mt-3 h-8 w-72" />
      <Skeleton className="mt-6 h-36 w-full" />

      <Skeleton className="mt-16 h-3 w-40" />
      <Skeleton className="mt-3 h-8 w-72" />
      <Skeleton className="mt-6 h-36 w-full" />
    </div>
  );
}
