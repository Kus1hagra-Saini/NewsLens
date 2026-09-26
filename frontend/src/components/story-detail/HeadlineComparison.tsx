import { useMemo } from "react";

import { formatDateTime } from "@/lib/format";
import { IconArrowUpRight } from "@/components/ui/Icon";
import type { ArticleInStory } from "@/api/types";

import { groupArticlesByOutlet, timeOf } from "./helpers";
import { StorySection } from "./primitives";

/**
 * FEATURE 4 — Same Story, Different Headlines
 *
 * A verbatim, side-by-side comparison of how each outlet titled the
 * story. Every headline is the exact scraped string from the source —
 * NewsLens never rewrites headlines. This section is the clearest way
 * to see framing at a glance, which is why the headlines themselves
 * are set at display size and everything else (outlet, timestamp,
 * source link) is deliberately kept small.
 *
 * Layout notes:
 *   - Each outlet is a stanza. Within a stanza we show every headline
 *     that outlet ran, ordered oldest → newest so a reader sees how
 *     that outlet's framing evolved (if it did).
 *   - Outlet stanzas are ordered by first-publication time (oldest
 *     outlet's first headline first), because "who broke it, and how"
 *     is a natural reading order.
 *   - The whole component reads as an editorial list, not a table.
 */
export function HeadlineComparison({ articles }: { articles: ArticleInStory[] }) {
  const groups = useMemo(() => {
    // Reuse the general grouping helper, then re-sort each group
    // oldest-first (the helper sorts newest-first for FullCoverage).
    const g = groupArticlesByOutlet(articles);
    for (const outlet of g) {
      outlet.articles.sort(
        (a, b) => timeOf(a.published_at) - timeOf(b.published_at),
      );
    }
    return g.sort((a, b) => {
      const aFirst = Math.min(
        ...a.articles.map((x) => timeOf(x.published_at)).filter((t) => t > 0),
      );
      const bFirst = Math.min(
        ...b.articles.map((x) => timeOf(x.published_at)).filter((t) => t > 0),
      );
      if (aFirst && bFirst && aFirst !== bFirst) return aFirst - bFirst;
      return a.name.localeCompare(b.name);
    });
  }, [articles]);

  if (groups.length === 0) return null;

  return (
    <StorySection
      eyebrow="Same story, different headlines"
      title="How each outlet titled it"
      lede="Every headline below is verbatim from the source. NewsLens never rewrites titles."
    >
      <ul className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
        {groups.map((group) => (
          <li key={group.slug} className="py-8 md:py-10">
            <div className="grid grid-cols-1 gap-x-8 md:grid-cols-[minmax(0,160px)_minmax(0,1fr)]">
              {/* Outlet label */}
              <div className="mb-4 md:mb-0">
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-primary">
                  {group.name}
                </div>
                <div className="tabular mt-1 text-[11px] text-ink-muted">
                  {group.articles.length} headline
                  {group.articles.length === 1 ? "" : "s"}
                </div>
              </div>

              {/* Stack of headlines from that outlet */}
              <ul className="space-y-6">
                {group.articles.map((article) => (
                  <li key={article.id} className="min-w-0">
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group block"
                    >
                      <h3 className="font-display text-[22px] leading-[1.25] tracking-[-0.005em] text-ink-primary transition-colors group-hover:text-accent sm:text-[26px]">
                        {article.headline}
                      </h3>
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-ink-muted">
                        <span className="tabular">
                          {formatDateTime(article.published_at)}
                        </span>
                        {article.author ? (
                          <>
                            <span aria-hidden className="text-ink-muted/40">·</span>
                            <span>By {article.author}</span>
                          </>
                        ) : null}
                        <span
                          aria-hidden
                          className="ml-auto inline-flex items-center gap-1 text-ink-muted transition-colors group-hover:text-accent"
                        >
                          Read on {group.name}
                          <IconArrowUpRight
                            size={11}
                            className="transition-transform duration-200 ease-editorial group-hover:translate-x-[1px] group-hover:-translate-y-[1px]"
                          />
                        </span>
                      </div>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </li>
        ))}
      </ul>
    </StorySection>
  );
}
