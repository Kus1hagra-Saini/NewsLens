import { ComingSoonPage } from "@/components/layout/ComingSoonPage";

/**
 * /trending — stories whose cross-outlet coverage is rising fastest.
 *
 * Signal (planned, Phase 5): change in the number of distinct outlets
 * covering the story inside a short recency window. Observable, no
 * opaque importance score.
 *
 * Ships as an "in development" placeholder in Phase 1 — the endpoint
 * (`GET /stories/trending?window=&limit=`) is approved but not yet
 * built.
 */
export default function Trending() {
  return (
    <ComingSoonPage
      eyebrow="Trending"
      title="Stories rising fastest across outlets"
      description="Coverage that is climbing sharply in the last few hours — measured by the change in distinct outlets covering the story over a short window, not by an opaque importance score."
      bullets={[
        "Change in distinct outlets covering the story over the last few hours",
        "Article count arriving inside the window",
        "Deep-link into each story's comparative coverage view",
        "Adjustable window (2h / 6h / 24h) once the backend endpoint lands",
      ]}
    />
  );
}
