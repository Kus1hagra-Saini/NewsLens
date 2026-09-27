import { Link } from "react-router-dom";
import type { ReactNode } from "react";

import { IconArrowUpRight } from "@/components/ui/Icon";

/**
 * Editorial "in development" placeholder — used by every route whose
 * real page ships in a later phase (Outlets, individual Outlet
 * Profile, Search, About). Matches the mastheading pattern of the
 * rest of the product so the empty state still reads as part of the
 * same publication.
 *
 * Extracted from the old pages/Placeholder.tsx (which lived under
 * pages/ and mixed the shared component with specific page bodies)
 * so any route can compose it.
 */
export function ComingSoonPage({
  eyebrow,
  title,
  description,
  bullets,
}: {
  eyebrow: string;
  title: string;
  description: string;
  bullets: ReactNode[];
}) {
  return (
    <div className="flex flex-col reveal-up">
      <header>
        <div className="mb-8 flex flex-wrap items-baseline justify-between gap-y-2 border-t-2 border-ink-primary pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
          <span className="text-ink-primary">{eyebrow}</span>
          <span className="text-ink-muted">In development</span>
        </div>
        <h1 className="font-display text-display-xl leading-[1.05] tracking-[-0.02em] text-ink-primary">
          {title}
        </h1>
        <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-secondary">
          {description}
        </p>
      </header>

      <section className="mt-12">
        <div className="mb-4 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
          <span className="inline-block h-[6px] w-[6px] rounded-full bg-accent" />
          On the roadmap
        </div>
        <ul className="grid gap-x-10 gap-y-3 border-y border-ink-primary/10 py-6 md:grid-cols-2">
          {bullets.map((b, i) => (
            <li
              key={i}
              className="flex items-start gap-3 text-[14px] leading-snug text-ink-secondary"
            >
              <span className="tabular mt-[2px] shrink-0 text-[11px] font-semibold text-accent">
                {(i + 1).toString().padStart(2, "0")}
              </span>
              <span>{b}</span>
            </li>
          ))}
        </ul>

        <div className="mt-6">
          <Link
            to="/"
            className="group inline-flex items-center gap-1.5 rounded-sm border-b border-ink-primary/20 px-0.5 py-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-primary transition-colors hover:border-accent hover:text-accent"
          >
            Back to home
            <IconArrowUpRight size={13} className="transition-transform duration-200 ease-editorial group-hover:translate-x-[1px] group-hover:-translate-y-[1px]" />
          </Link>
        </div>
      </section>
    </div>
  );
}
