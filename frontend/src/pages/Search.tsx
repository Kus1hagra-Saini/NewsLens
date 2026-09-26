import { ComingSoonPage } from "@/components/layout/ComingSoonPage";

/**
 * /search — full-text search across every ingested article.
 *
 * Ships as an "in development" placeholder in Phase 1. The real page
 * lands in Phase 4 and consumes the existing `GET /search?q=`
 * endpoint (PostgreSQL FTS with ts_rank + ts_headline snippets)
 * already served by the committed backend at 0e18436.
 */
export default function Search() {
  return (
    <ComingSoonPage
      eyebrow="Search"
      title="Full-text search across every article"
      description="Ranked full-text search over every ingested article body, powered by PostgreSQL's built-in FTS — no external search service, no vendor lock-in."
      bullets={[
        "Ranked full-text search across every ingested article body",
        "Filter by outlet, framing label and date window",
        "Highlighted snippet under each result",
        "Deep-link back into the story a matching article belongs to",
      ]}
    />
  );
}
