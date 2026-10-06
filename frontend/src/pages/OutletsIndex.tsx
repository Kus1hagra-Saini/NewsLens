import { IconArrowUpRight } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import {
  OUTLET_DIRECTORY,
  OUTLET_RATING_HELPER,
  type OutletDirectoryEntry,
  type OutletRating,
} from "@/lib/outlets";

/**
 * /outlets — the simple directory of publications NewsLens tracks.
 *
 * The purpose is modest and deliberately so: "these are the 15 Indian
 * news publications NewsLens compares, with a short note on each."
 * No per-outlet analytics, charts, framing numbers or coverage stats
 * are shown here — the comparative work lives on each Story Detail
 * page.
 *
 * External publication-level ratings (from Media Bias/Fact Check)
 * are presented verbatim with an explicit "External rating" label so
 * a reader never mistakes them for a NewsLens-generated political
 * classification and never confuses them with the article-level
 * framing indicator.
 *
 * Layout mirrors the rest of the site: a masthead strip, a Fraunces
 * display headline with a short lede, then a responsive card grid
 * (1 / 2 / 3 columns on mobile / tablet / desktop). All typography,
 * colour and border tokens come from the existing editorial design
 * system; no new tokens or components are introduced.
 */
export default function OutletsIndex() {
  const outlets = OUTLET_DIRECTORY;

  return (
    <div className="flex flex-col reveal-up">
      {/* ───────────────  Masthead  ─────────────── */}
      <header>
        <div className="mb-8 flex flex-wrap items-baseline justify-between gap-y-2 border-t-2 border-ink-primary pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
          <div className="flex items-center gap-3">
            <span className="text-ink-primary">Our News Sources</span>
            <span className="hidden sm:inline text-ink-muted/50">/</span>
            <span className="hidden sm:inline">Publications tracked by NewsLens</span>
          </div>
          <div className="tabular text-ink-muted">
            {outlets.length} {outlets.length === 1 ? "publication" : "publications"}
          </div>
        </div>

        <h1 className="font-display text-display-xl leading-[1.05] tracking-[-0.02em] text-ink-primary sm:text-display-2xl">
          <span>The </span>
          <span className="italic text-accent">15 publications</span>
          <span> we compare.</span>
        </h1>
        <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-secondary">
          NewsLens compares coverage from 15 Indian news publications to show
          how the same stories can be covered differently. The ratings shown
          below are external, publication-level labels from third-party
          organisations — never a NewsLens judgment about any individual
          article.
        </p>
      </header>

      {/* ───────────────  Directory grid  ─────────────── */}
      <section className="mt-14">
        <ul
          className={cn(
            "grid grid-cols-1 gap-x-6 gap-y-6",
            "md:grid-cols-2 md:gap-x-8 md:gap-y-8",
            "lg:grid-cols-3",
          )}
        >
          {outlets.map((outlet) => (
            <li key={outlet.slug}>
              <OutletCard outlet={outlet} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function OutletCard({ outlet }: { outlet: OutletDirectoryEntry }) {
  const host = hostFromUrl(outlet.website);

  return (
    <article
      className={cn(
        "group flex h-full flex-col",
        "border-t border-ink-primary/15 pt-5",
      )}
    >
      {/* Outlet name — small Fraunces heading, in line with the rest of
          the editorial type scale. */}
      <h2 className="font-display text-[22px] leading-[1.2] tracking-[-0.01em] text-ink-primary">
        {outlet.name}
      </h2>

      {/* Site host as a tiny meta line. */}
      <div className="mt-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
        {host}
      </div>

      {/* One- to two-sentence description. */}
      <p className="mt-3 text-[13.5px] leading-relaxed text-ink-secondary">
        {outlet.description}
      </p>

      {/* Rating + external-link row sits at the bottom of the card so
          cards align in a grid regardless of description length. */}
      <div className="mt-5 flex-1" />
      <RatingLine rating={outlet.rating} />

      <a
        href={outlet.website}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "mt-4 inline-flex items-center gap-1.5 self-start",
          "text-[11px] font-semibold uppercase tracking-[0.14em]",
          "text-ink-muted hover:text-accent transition-colors",
        )}
      >
        <span>Visit site</span>
        <IconArrowUpRight size={12} />
      </a>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Rating line — the external label, clearly scoped and non-political
// in wording. Uses existing surface-alt + ink tokens; no new colour
// bucket per rating, because the point of this page is NOT to visually
// rank outlets by lean.
// ---------------------------------------------------------------------------

function RatingLine({ rating }: { rating: OutletRating }) {
  return (
    <div
      className={cn(
        "mt-1 flex flex-col gap-1.5 rounded-md border border-subtle",
        "bg-surface-alt/60 px-3 py-2.5",
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
          External publication rating
        </span>
        <span className="text-[12.5px] font-semibold tabular text-ink-primary">
          {rating}
        </span>
      </div>
      <p className="text-[11.5px] leading-snug text-ink-muted">
        {OUTLET_RATING_HELPER[rating]} Source: Media Bias/Fact Check.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hostFromUrl(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}
