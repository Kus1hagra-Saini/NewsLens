import { useMemo } from "react";
import { useParams } from "react-router-dom";

import { DisclaimerFootnote } from "@/components/dashboard/DisclaimerFootnote";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { Skeleton } from "@/components/ui/Skeleton";
import { ArticlesByOutlet } from "@/components/story-detail/ArticlesByOutlet";
import { CoverageGaps } from "@/components/story-detail/CoverageGaps";
import { FramingSection } from "@/components/story-detail/FramingSection";
import { HeadlineComparison } from "@/components/story-detail/HeadlineComparison";
import { MediaBiasDistribution } from "@/components/story-detail/MediaBiasDistribution";
import { OutletEmphasis } from "@/components/story-detail/OutletEmphasis";
import { SourceVoicesSection } from "@/components/story-detail/SourceVoices";
import { StoryHeader } from "@/components/story-detail/StoryHeader";
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
import type { StoryDetail as StoryDetailPayload } from "@/api/types";

/**
 * /stories/:id — the flagship NewsLens analytical experience.
 *
 * This page answers, top to bottom, one editorial question:
 *
 *   "What is happening in this story, and how differently are
 *   different outlets covering it?"
 *
 * Section order (see the design brief):
 *
 *   1. StoryHeader
 *   2. StorySummary               (factual "story in one minute")
 *   3. MediaBiasDistribution      (publication-level, external ratings)
 *   4. WhatDiffers                (the analytic counterpart to summary)
 *   5. OutletEmphasis
 *   6. HeadlineComparison
 *   7. FramingSection             (article-level framing — NOT political bias)
 *   8. SourceVoicesSection        (who is being heard?)
 *   9. CoverageGaps
 *  10. ArticlesByOutlet           (full coverage)
 *
 * MediaBiasDistribution and FramingSection are DIFFERENT concepts:
 *   - Bias distribution is publication-level and comes from external
 *     third-party ratings (currently MBFC).
 *   - Framing is article-level (critical / neutral / supportive) and
 *     comes from our LLM analysis of each article's text.
 * The two are rendered in distinct sections and use distinct
 * vocabularies so a reader never conflates them.
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
// Body composition — every section stands on its own; the shell just
// arranges them and inserts the section rule between visible sections.
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
      headlines: outletGroups.length > 0,
      framing: framingRows.length > 0,
      sources: sourceTotals > 0 || quoteCount > 0,
      gaps: gapsRows.some((r) => r.items.length > 0),
      full: outletGroups.length > 0,
    };
  }, [articles, story.comparison, story.summary, story.bias_distribution]);

  interface SectionEntry {
    key: string;
    visible: boolean;
    node: React.ReactNode;
  }

  const sections: SectionEntry[] = [
    {
      key: "summary",
      visible: visibility.summary,
      node: <StorySummary story={story} />,
    },
    {
      key: "bias",
      visible: visibility.bias,
      node: (
        <MediaBiasDistribution distribution={story.bias_distribution} />
      ),
    },
    {
      key: "differs",
      visible: visibility.differs,
      node: <WhatDiffers story={story} />,
    },
    {
      key: "emphasis",
      visible: visibility.emphasis,
      node: (
        <OutletEmphasis comparison={story.comparison} articles={articles} />
      ),
    },
    {
      key: "headlines",
      visible: visibility.headlines,
      node: <HeadlineComparison articles={articles} />,
    },
    {
      key: "framing",
      visible: visibility.framing,
      node: <FramingSection story={story} articles={articles} />,
    },
    {
      key: "sources",
      visible: visibility.sources,
      node: <SourceVoicesSection articles={articles} />,
    },
    {
      key: "gaps",
      visible: visibility.gaps,
      node: (
        <CoverageGaps comparison={story.comparison} articles={articles} />
      ),
    },
    {
      key: "full",
      visible: visibility.full,
      node: <ArticlesByOutlet articles={articles} />,
    },
  ];

  const visibleSections = sections.filter((s) => s.visible);

  return (
    <article className="flex flex-col">
      <StoryHeader story={story} />

      {visibleSections.length > 0 ? (
        <div className="mt-14 md:mt-20">
          {visibleSections.map((entry, i) => (
            <div key={entry.key}>
              {i > 0 ? <SectionRule /> : null}
              {entry.node}
            </div>
          ))}
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
