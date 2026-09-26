import { Link } from "react-router-dom";
import { IconArrowUpRight } from "@/components/ui/Icon";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-5 text-center reveal-up">
      <div className="tabular font-display text-[6rem] font-semibold leading-none text-ink-primary">
        404
      </div>
      <div className="max-w-sm space-y-1">
        <h1 className="font-display text-display-lg text-ink-primary">Page not found</h1>
        <p className="text-sm text-ink-muted">
          That route doesn&rsquo;t exist. Head back to the dashboard.
        </p>
      </div>
      <Link
        to="/"
        className="group inline-flex items-center gap-1.5 rounded-sm border-b border-ink-primary/20 px-0.5 py-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-primary transition-colors hover:border-accent hover:text-accent"
      >
        Back to dashboard
        <IconArrowUpRight size={13} className="transition-transform duration-200 ease-editorial group-hover:translate-x-[1px] group-hover:-translate-y-[1px]" />
      </Link>
    </div>
  );
}
