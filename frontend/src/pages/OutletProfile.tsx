import { useParams } from "react-router-dom";
import { ComingSoonPage } from "@/components/layout/ComingSoonPage";

/**
 * /outlets/:slug — per-outlet profile page.
 *
 * Ships as an "in development" placeholder in Phase 1. The real page
 * lands in Phase 4 and consumes `GET /outlets/{slug}` and
 * `GET /outlets/{slug}/stats` from the committed backend, plus a
 * planned `GET /stories?outlet=<slug>` filter for the "recent stories"
 * section (Phase 4, requires backend approval before implementation).
 */
export default function OutletProfile() {
  const { slug } = useParams<{ slug: string }>();
  const displaySlug = slug ?? "(unknown)";
  return (
    <ComingSoonPage
      eyebrow={`Outlet · ${displaySlug}`}
      title="Outlet profile"
      description="Detailed profile of this outlet's coverage — recent stories, cadence over the last 30 days, dominant themes, and the observed framing pattern."
      bullets={[
        "Outlet metadata and RSS source",
        "Recent stories this outlet contributed to",
        "Coverage volume by day for the last 30 days",
        "Dominant themes and quoted-source distribution",
        "Average framing on the observed indicator — with disclaimer",
      ]}
    />
  );
}
