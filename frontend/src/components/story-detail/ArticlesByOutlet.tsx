import { useMemo, useState } from "react";

import { cn } from "@/lib/cn";
import {
  formatCount,
  formatDateTime,
  formatRelative,
  formatSignedDecimal,
} from "@/lib/format";
import { FRAMING_META } from "@/lib/constants";
import { IconArrowUpRight, IconInfo } from "@/components/ui/Icon";
import type {
  ArticleAnalysisPayload,
  ArticleInStory,
} from "@/api/types";

import {
  entitiesFromPayload,
  groupArticlesByOutlet,
  normaliseFramingLabel,
  type CleanQuotedSource,
  type EntitiesRollup,
} from "./helpers";
import { Chip, DataCell, StorySection } from "./primitives";

/**
 * FEATURE 8 — Full Coverage
 *
 * The article-level index for a story, grouped by outlet. Replaces
 * the flat article list with a per-outlet stanza:
 *
 *   - Outlet heading with article count.
 *   - Every article as a collapsed row: framing chip, theme chips,
 *     verbatim headline, timestamp, source link.
 *   - Detailed article analysis expands inline on demand.
 *
 * This keeps the page short by default even on stories with many
 * articles, while still exposing every piece of analytical evidence
 * on request. Progressive disclosure is the whole design here.
 */
export function ArticlesByOutlet({ articles }: { articles: ArticleInStory[] }) {
  const groups = useMemo(() => groupArticlesByOutlet(articles), [articles]);
  if (groups.length === 0) return null;

  const outletCount = groups.length;
  const articleCount = articles.length;

  return (
    <StorySection
      eyebrow="Full coverage"
      title="Every article in this story"
      lede={`${formatCount(articleCount)} article${
        articleCount === 1 ? "" : "s"
      } across ${formatCount(outletCount)} outlet${
        outletCount === 1 ? "" : "s"
      }. Expand any article to see the underlying analysis.`}
    >
      <ol className="space-y-10 md:space-y-12">
        {groups.map((group) => (
          <li key={group.slug}>
            <header className="mb-4 flex items-baseline justify-between gap-3 border-t border-ink-primary/25 pt-3">
              <div className="min-w-0">
                <div className="font-display text-[22px] leading-tight text-ink-primary sm:text-[24px]">
                  {group.name}
                </div>
                <div className="tabular mt-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
                  {formatCount(group.articles.length)} article
                  {group.articles.length === 1 ? "" : "s"}
                </div>
              </div>
            </header>

            <ul className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
              {group.articles.map((article) => (
                <ArticleCard key={article.id} article={article} />
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </StorySection>
  );
}

// ---------------------------------------------------------------------------
// One collapsible article row
// ---------------------------------------------------------------------------

function ArticleCard({ article }: { article: ArticleInStory }) {
  const [expanded, setExpanded] = useState(false);
  const framingKey = normaliseFramingLabel(article.analysis?.framing_label);
  const framingMeta = framingKey ? FRAMING_META[framingKey] : null;

  const themes = (article.analysis?.key_themes ?? []).filter(
    (t): t is string => typeof t === "string" && t.trim().length > 0,
  );
  const themePreview = themes.slice(0, 3);
  const extraThemeCount = Math.max(0, themes.length - themePreview.length);

  const canExpand = Boolean(article.analysis);

  return (
    <li className="py-6">
      <div className="grid grid-cols-1 gap-x-6 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          {/* Framing + theme chips */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {framingMeta ? (
              <FramingChip label={framingMeta.label} colorVar={framingMeta.colorVar} />
            ) : article.analysis?.framing_label ? (
              <FramingChip label={article.analysis.framing_label} colorVar={null} />
            ) : null}
            {themePreview.map((t, i) => (
              <Chip key={`${t}-${i}`}>{t}</Chip>
            ))}
            {extraThemeCount > 0 ? (
              <Chip tone="muted">+{extraThemeCount} more</Chip>
            ) : null}
          </div>

          {/* Verbatim headline */}
          <h3 className="font-display text-[19px] leading-snug tracking-[-0.005em] text-ink-primary sm:text-[22px]">
            <a
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors hover:text-accent"
            >
              {article.headline}
            </a>
          </h3>

          {/* Meta row */}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-ink-muted">
            <span className="tabular">{formatDateTime(article.published_at)}</span>
            {article.author ? (
              <>
                <span aria-hidden className="text-ink-muted/40">·</span>
                <span>By {article.author}</span>
              </>
            ) : null}
            <span aria-hidden className="text-ink-muted/40">·</span>
            <span>{article.processing_state}</span>
          </div>
        </div>

        {/* Right column: actions */}
        <div className="mt-3 flex shrink-0 items-start gap-3 md:mt-0 md:flex-col md:items-end">
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-1.5 rounded-sm border-b border-ink-primary/20 px-0.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-primary transition-colors hover:border-accent hover:text-accent"
          >
            Read source
            <IconArrowUpRight
              size={11}
              className="transition-transform duration-200 ease-editorial group-hover:translate-x-[1px] group-hover:-translate-y-[1px]"
            />
          </a>
          {canExpand ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              className="inline-flex items-center gap-1.5 rounded-sm px-0.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted transition-colors hover:text-accent"
            >
              {expanded ? "Hide analysis" : "Show analysis"}
            </button>
          ) : (
            <span className="text-[11px] uppercase tracking-[0.12em] text-ink-muted">
              No analysis
            </span>
          )}
        </div>
      </div>

      {/* Collapsible detailed analysis */}
      {expanded && article.analysis ? (
        <ArticleAnalysisPanel analysis={article.analysis} />
      ) : null}
    </li>
  );
}

// ---------------------------------------------------------------------------
// The expanded analysis panel
// ---------------------------------------------------------------------------

function ArticleAnalysisPanel({
  analysis,
}: {
  analysis: ArticleAnalysisPayload;
}) {
  const evidence = (analysis.evidence_snippets ?? []).filter(
    (s): s is string => typeof s === "string" && s.trim().length > 0,
  );
  const entities = entitiesFromPayload(analysis);
  const quotes = normaliseInlineQuotes(analysis);

  return (
    <div className="mt-6 space-y-6 border-l-2 border-ink-primary/10 pl-5">
      {/* Data strip */}
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3">
        <DataCell
          label="Framing"
          value={
            <span className="tabular">
              {formatSignedDecimal(analysis.framing_score, 2)}
            </span>
          }
        />
        <DataCell
          label="Confidence"
          value={
            <span className="tabular">
              {analysis.framing_confidence !== null
                ? `${Math.round(analysis.framing_confidence * 100)}%`
                : "—"}
            </span>
          }
        />
        <DataCell
          label="Headline sentiment"
          value={
            <span className="tabular">
              {formatSignedDecimal(analysis.headline_sentiment, 2)}
            </span>
          }
        />
        <DataCell
          label="Body sentiment"
          value={
            <span className="tabular">
              {formatSignedDecimal(analysis.body_sentiment, 2)}
            </span>
          }
        />
      </div>

      {/* Evidence snippets */}
      {evidence.length > 0 ? (
        <div>
          <SubHeader>Evidence snippets</SubHeader>
          <ul className="mt-2 space-y-3 border-l-2 border-accent/30 pl-4">
            {evidence.map((snippet, i) => (
              <li
                key={i}
                className="font-display text-[14.5px] leading-[1.55] italic text-ink-secondary"
              >
                &ldquo;{snippet}&rdquo;
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Quoted sources */}
      {quotes.length > 0 ? (
        <div>
          <SubHeader>Quoted sources</SubHeader>
          <ul className="mt-2 space-y-3">
            {quotes.map((q, i) => (
              <li key={i} className="text-[13.5px] leading-relaxed text-ink-secondary">
                <span className="font-semibold text-ink-primary">
                  {q.speaker}
                </span>
                {q.affiliation ? (
                  <span className="text-ink-muted"> · {q.affiliation}</span>
                ) : null}
                {q.quote ? (
                  <>
                    <br />
                    <span className="font-display italic">
                      &ldquo;{q.quote}&rdquo;
                    </span>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Entities */}
      {hasAnyEntity(entities) ? (
        <div>
          <SubHeader>Entities mentioned</SubHeader>
          <div className="mt-2 space-y-2">
            {entities.people.length > 0 ? (
              <EntityRow label="People" values={entities.people} />
            ) : null}
            {entities.organizations.length > 0 ? (
              <EntityRow label="Organizations" values={entities.organizations} />
            ) : null}
            {entities.locations.length > 0 ? (
              <EntityRow label="Locations" values={entities.locations} />
            ) : null}
            {entities.other.length > 0 ? (
              <EntityRow label="Other" values={entities.other} />
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="flex items-center gap-1.5 text-[10.5px] text-ink-muted">
        <IconInfo size={11} />
        Analysed {formatRelative(analysis.analyzed_at)}
      </div>
    </div>
  );
}

function SubHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
      {children}
    </div>
  );
}

function EntityRow({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] items-baseline gap-x-4">
      <div className="text-[11px] font-medium text-ink-muted">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {values.map((v, i) => (
          <Chip key={`${v}-${i}`} tone="muted">
            {v}
          </Chip>
        ))}
      </div>
    </div>
  );
}

function FramingChip({
  label,
  colorVar,
}: {
  label: string;
  colorVar: string | null;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] text-[11px] font-semibold uppercase tracking-[0.08em]",
        "border-subtle bg-surface-alt text-ink-primary",
      )}
    >
      <span
        aria-hidden
        className={cn("inline-block h-2 w-2 rounded-sm", colorVar ? "" : "bg-ink-muted")}
        style={colorVar ? { background: colorVar } : undefined}
      />
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Local (per-article) quote normalisation — a thin wrapper over the
// shared helper's schema, but scoped to a single analysis payload so
// ArticleCard doesn't have to know about the outlet on `CleanQuotedSource`.
// ---------------------------------------------------------------------------

interface InlineQuote {
  speaker: string;
  affiliation: string | null;
  quote: string;
}

function normaliseInlineQuotes(
  analysis: ArticleAnalysisPayload,
): InlineQuote[] {
  const raw = analysis.quoted_sources;
  if (!Array.isArray(raw)) return [];
  const out: InlineQuote[] = [];
  for (const entry of raw) {
    if (!entry) continue;
    if (typeof entry === "string") {
      const trimmed = entry.trim();
      if (!trimmed) continue;
      out.push({
        speaker: "Unattributed",
        affiliation: null,
        quote: trimmed.replace(/^["“”'‘’]+|["“”'‘’]+$/g, ""),
      });
      continue;
    }
    if (typeof entry !== "object") continue;
    const obj = entry as Record<string, unknown>;
    const speaker =
      typeof obj.speaker === "string" && obj.speaker.trim().length > 0
        ? obj.speaker.trim()
        : "Unattributed";
    const affiliation =
      typeof obj.affiliation === "string" && obj.affiliation.trim().length > 0
        ? obj.affiliation.trim()
        : null;
    const quote =
      typeof obj.quote === "string" ? obj.quote.trim() : "";
    if (!quote && speaker === "Unattributed") continue;
    out.push({
      speaker,
      affiliation,
      quote: quote.replace(/^["“”'‘’]+|["“”'‘’]+$/g, ""),
    });
  }
  return out;
}

function hasAnyEntity(e: EntitiesRollup): boolean {
  return (
    e.people.length > 0 ||
    e.organizations.length > 0 ||
    e.locations.length > 0 ||
    e.other.length > 0
  );
}

// The unused import warning-silencer: keep the CleanQuotedSource type
// visible in this module so the shared helper's public API stays
// used by more than one section.
export type { CleanQuotedSource };
