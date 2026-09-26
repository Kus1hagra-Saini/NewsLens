import { DashboardHeader } from "@/components/dashboard/DashboardHeader";
import { DisclaimerFootnote } from "@/components/dashboard/DisclaimerFootnote";
import { FramingDonut } from "@/components/dashboard/FramingDonut";
import { KpiRow } from "@/components/dashboard/KpiRow";
import { RecentStories } from "@/components/dashboard/RecentStories";
import { TrendsChart } from "@/components/dashboard/TrendsChart";
import { ErrorState } from "@/components/ui/States";
import { useOverview } from "@/api/queries";

/**
 * NewsLens dashboard.
 *
 * Editorial rhythm: masthead → coverage snapshot → coverage volume →
 * framing distribution → latest coverage → framing footnote. Sections
 * are separated by generous vertical space rather than boxed cards.
 *
 * Error handling — deliberate:
 *   - The /overview call powers the masthead status chip AND the KPI
 *     row. If it fails we surface a rich diagnostic in place of the
 *     KPI row (showing endpoint, base URL, status, detail) but STILL
 *     render the trend chart, framing chart and stories feed below —
 *     each has its own retry. Partial failure never blanks the page.
 *   - The masthead itself always renders (with the tagline) because
 *     it doesn't depend on the API.
 */
export default function Dashboard() {
  const overview = useOverview();

  return (
    <div className="flex flex-col">
      <DashboardHeader
        latestRun={overview.data?.latest_ingestion_run ?? null}
        loading={overview.isLoading}
      />

      <div className="mt-14">
        {overview.isError ? (
          <ErrorState
            title="Couldn't load coverage snapshot"
            error={overview.error}
            onRetry={() => overview.refetch()}
          />
        ) : (
          <KpiRow data={overview.data} loading={overview.isLoading} />
        )}
      </div>

      <div className="mt-16">
        <TrendsChart />
      </div>

      <div className="mt-16">
        <FramingDonut windowDays={7} />
      </div>

      <div className="mt-16">
        <RecentStories />
      </div>

      <DisclaimerFootnote />
    </div>
  );
}
