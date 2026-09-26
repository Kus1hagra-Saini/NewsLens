import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";

/**
 * Shared editorial primitives used by the Story Detail sections.
 *
 * The Story Detail page deliberately avoids the SaaS "grid of rounded
 * cards" pattern in favour of typographic hierarchy and thin editorial
 * hairlines. The primitives here are the reusable pieces of that
 * language: a section shell, a kicker line, a discreet chip, a soft
 * back-link and a tiny data cell.
 */

// ---------------------------------------------------------------------------
// Back-to-list link
// ---------------------------------------------------------------------------

export function BackLink({
  to = "/stories",
  label = "Back to stories",
}: {
  to?: string;
  label?: string;
}) {
  return (
    <div className="mb-6">
      <Link
        to={to}
        className="group inline-flex items-center gap-1.5 rounded-sm border-b border-transparent px-0.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted transition-colors hover:border-accent hover:text-accent"
      >
        <span
          aria-hidden
          className="transition-transform duration-200 ease-editorial group-hover:-translate-x-[2px]"
        >
          ←
        </span>
        {label}
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section shell — bounded by hairlines rather than a card.
// ---------------------------------------------------------------------------

/**
 * A vertical section with a kicker + title + optional aside. Sections
 * are bounded top and bottom by whatever the parent chooses; the
 * component itself only owns the internal layout so surrounding rules
 * flow through the page.
 */
export function StorySection({
  eyebrow,
  title,
  lede,
  aside,
  children,
  className,
  id,
}: {
  eyebrow: ReactNode;
  title: ReactNode;
  lede?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cn("reveal-up", className)}>
      <header className="mb-6 flex flex-col gap-3 md:mb-8 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0 max-w-2xl">
          <SectionKicker>{eyebrow}</SectionKicker>
          <h2 className="mt-2 font-display text-[26px] leading-[1.15] tracking-[-0.01em] text-ink-primary sm:text-[30px]">
            {title}
          </h2>
          {lede ? (
            <p className="mt-2 text-[13.5px] leading-relaxed text-ink-secondary">
              {lede}
            </p>
          ) : null}
        </div>
        {aside ? <div className="shrink-0 self-end">{aside}</div> : null}
      </header>
      {children}
    </section>
  );
}

/**
 * A small all-caps kicker line with a coral dot — the editorial
 * signpost that opens every section. Rendered as a standalone so
 * MetaLabels can also use it.
 */
export function SectionKicker({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-muted">
      <span className="inline-block h-[6px] w-[6px] rounded-full bg-accent" />
      <span>{children}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Meta cell — small label + value used in the header data-strip.
// ---------------------------------------------------------------------------

export function MetaCell({
  label,
  value,
  tone,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
        {label}
      </div>
      <div
        className={cn(
          "tabular mt-1 font-display text-[19px] font-semibold leading-none text-ink-primary",
          tone,
        )}
      >
        {value}
      </div>
    </div>
  );
}

/**
 * A denser data cell for inline data-strips inside subsections. Same
 * shape as MetaCell but with a smaller footprint.
 */
export function DataCell({
  label,
  value,
}: {
  label: ReactNode;
  value: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
        {label}
      </div>
      <div className="mt-0.5 text-[14px] font-medium text-ink-primary">{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chip — a thin outlined pill used for themes / entities / stances.
// ---------------------------------------------------------------------------

export function Chip({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  tone?: "default" | "muted" | "accent";
  className?: string;
}) {
  const toneCls = {
    default:
      "border-subtle bg-surface-alt text-ink-secondary",
    muted:
      "border-transparent bg-surface-alt/60 text-ink-muted",
    accent:
      "border-accent/25 bg-accent-soft text-accent-ink",
  }[tone];

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-[3px] text-[11.5px] font-medium leading-none",
        toneCls,
        className,
      )}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// A slim horizontal hairline — used between subsections without cards.
// ---------------------------------------------------------------------------

export function SectionRule({ className }: { className?: string }) {
  return <hr className={cn("editorial-rule my-16 md:my-20", className)} />;
}
