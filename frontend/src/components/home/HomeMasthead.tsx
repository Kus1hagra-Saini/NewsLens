import { BRAND_NAME } from "@/lib/constants";

/**
 * Restrained editorial masthead for the homepage.
 *
 * Sits beneath the sticky TopNav and reads as a publication front-page
 * strip rather than a marketing hero: a small caps NEWSLENS kicker, a
 * large display headline, and a single-sentence explainer. No CTAs, no
 * gradient panel, no illustration, no fake statistics.
 *
 * The italic on the second clause is the one visual accent — same
 * treatment the old dashboard header used, so the editorial voice is
 * consistent with the rest of the site.
 */
export function HomeMasthead() {
  return (
    <header className="reveal-up">
      {/* Masthead strip — the thin 2px rule at the top of a newspaper. */}
      <div className="mb-8 flex flex-wrap items-baseline justify-between gap-y-2 border-t-2 border-ink-primary pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
        <div className="flex items-center gap-3">
          <span className="text-ink-primary">{BRAND_NAME}</span>
          <span className="hidden sm:inline text-ink-muted/50">/</span>
          <span className="hidden sm:inline">Comparative news coverage, India</span>
        </div>
        <div className="tabular text-ink-muted">{todayLabel()}</div>
      </div>

      <div className="max-w-3xl">
        <h1 className="font-display leading-[1.05] tracking-[-0.02em] text-ink-primary text-display-xl sm:text-display-2xl">
          <span>See how the news</span>{" "}
          <span className="italic text-accent">is being covered</span>
          <span>.</span>
        </h1>
        <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-secondary">
          Compare how India&rsquo;s news outlets cover the same stories &mdash;
          what they emphasize, how they frame them, and whose voices appear.
        </p>
      </div>
    </header>
  );
}

function todayLabel(): string {
  const d = new Date();
  return d
    .toLocaleDateString("en-IN", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    })
    .toUpperCase();
}
