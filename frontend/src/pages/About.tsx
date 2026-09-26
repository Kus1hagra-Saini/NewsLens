import { ComingSoonPage } from "@/components/layout/ComingSoonPage";

/**
 * /about — how NewsLens compares coverage, and what the framing
 * indicator means.
 *
 * The bulk of the page is still an "in development" placeholder while
 * the full methodology write-up lands in Phase 4. The Media Bias
 * Distribution methodology block below it is filed here as soon as
 * that feature ships so the visualisation on Story Detail always has
 * a place a reader can click through to.
 */
export default function About() {
  return (
    <div className="flex flex-col">
      <ComingSoonPage
        eyebrow="About & methodology"
        title="How NewsLens compares coverage"
        description="What the framing indicator means, how it is computed from article signals, and how NewsLens clusters articles into stories and compares outlet coverage."
        bullets={[
          "The framing indicator — article-level, non-political, with disclaimer",
          "How stories are clustered from article embeddings",
          "How coverage comparisons are generated and re-generated",
          "Coverage volume and framing distribution at a glance",
          "The five Indian outlets currently monitored",
        ]}
      />

      <BiasMethodology />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Media Bias Distribution methodology — the transparency block the
// Story Detail visualisation links to.
// ---------------------------------------------------------------------------

function BiasMethodology() {
  return (
    <section className="mt-20 reveal-up" id="media-bias-distribution">
      <header className="mb-6 max-w-3xl">
        <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-muted">
          <span className="inline-block h-[6px] w-[6px] rounded-full bg-accent" />
          <span>Media Bias Distribution — methodology</span>
        </div>
        <h2 className="font-display text-[28px] leading-[1.15] tracking-[-0.01em] text-ink-primary sm:text-[32px]">
          How the bias distribution on a story page is calculated
        </h2>
        <p className="mt-3 text-[14px] leading-relaxed text-ink-secondary">
          The distribution shown on a Story Detail page describes the
          publications covering that story, based on ratings published
          by third-party organisations. It is separate from the article-
          level framing indicator NewsLens computes from an article's
          own text.
        </p>
      </header>

      <ul className="grid gap-x-10 gap-y-5 border-y border-ink-primary/10 py-6 md:grid-cols-2">
        <MethodologyPoint
          n={1}
          title="Publication-level, not article-level"
          body="Ratings describe an outlet's editorial position on average, over time. They are not a claim about the story or about any single article on the story."
        />
        <MethodologyPoint
          n={2}
          title="Sourced from documented third parties"
          body="Ratings come from external organisations — currently Media Bias/Fact Check — and each source's rating is preserved verbatim, with a link back to the source's own page."
        />
        <MethodologyPoint
          n={3}
          title="Only rated outlets contribute"
          body="The distribution is calculated from the outlets covering the story that have a documented rating. Unrated outlets are reported as unrated — never silently placed in a bucket."
        />
        <MethodologyPoint
          n={4}
          title="Article-level framing is separate"
          body="NewsLens's own framing indicator (Critical / Neutral / Supportive) is a per-article signal computed from that article's text. It uses non-political vocabulary and lives in its own section of the Story page."
        />
        <MethodologyPoint
          n={5}
          title="Eligibility rules"
          body="The distribution appears only for stories with coverage from at least 3 distinct outlets, of which at least 3 are rated. Below either threshold, a short explanatory note appears in place of the visualisation."
        />
        <MethodologyPoint
          n={6}
          title="No political claim about the story"
          body="Rules out phrasings such as 'this story is X% left' or 'right-biased article'. The distribution reports the mix of publications covering a story, not the political position of the story itself."
        />
      </ul>

      <p className="mt-6 max-w-3xl text-[12.5px] leading-relaxed text-ink-muted">
        NewsLens does not generate publication-level bias ratings.
        Ratings are hand-recorded from each external source's own page,
        stored with the source name, the exact published label, and the
        source URL, and can be re-verified from the source-details
        expander on any Story Detail page.
      </p>
    </section>
  );
}

function MethodologyPoint({
  n,
  title,
  body,
}: {
  n: number;
  title: string;
  body: string;
}) {
  return (
    <li className="flex items-start gap-3">
      <span className="tabular mt-[3px] shrink-0 text-[11px] font-semibold text-accent">
        {n.toString().padStart(2, "0")}
      </span>
      <div className="min-w-0">
        <div className="font-display text-[16px] leading-tight text-ink-primary">
          {title}
        </div>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-secondary">
          {body}
        </p>
      </div>
    </li>
  );
}
