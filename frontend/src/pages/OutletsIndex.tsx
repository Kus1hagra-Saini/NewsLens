import { ComingSoonPage } from "@/components/layout/ComingSoonPage";

/**
 * /outlets — the Indian news outlets NewsLens is monitoring.
 *
 * Ships as an "in development" placeholder in Phase 1. The real page
 * lands in Phase 4 and consumes the existing `GET /outlets` +
 * `GET /outlets/{slug}/stats` endpoints already served by the
 * committed backend at 0e18436.
 */
export default function OutletsIndex() {
  return (
    <ComingSoonPage
      eyebrow="Outlets"
      title="The outlets NewsLens is tracking"
      description="A short profile of every monitored Indian outlet — coverage volume, recent stories, and the observed 30-day framing pattern (with the framing-indicator disclaimer preserved on every value)."
      bullets={[
        "Coverage volume and cadence for each outlet",
        "Recent stories the outlet contributed to",
        "Dominant themes on a 30-day window",
        "Average framing on the observed indicator — with disclaimer",
        "Currently monitored: The Hindu, Times of India, Indian Express, NDTV, Hindustan Times",
      ]}
    />
  );
}
