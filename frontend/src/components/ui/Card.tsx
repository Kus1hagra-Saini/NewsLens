import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
  padding?: "sm" | "md" | "lg" | "none";
  /**
   * "surface" (default) — subtle border + shadow, the classic card.
   * "plain"           — no border, no shadow, no background; useful when
   *                     the section wants an open editorial feel with
   *                     only its heading and hairlines for framing.
   */
  variant?: "surface" | "plain";
}

/**
 * Surface primitive. We keep the option to render as a card, but the
 * editorial layout deliberately prefers `variant="plain"` for most
 * sections and reserves the card treatment for genuinely grouped
 * content.
 */
export function Card({
  interactive,
  padding = "md",
  variant = "surface",
  className,
  ...rest
}: CardProps) {
  const paddingCls = {
    none: "",
    sm: "p-4",
    md: "p-5",
    lg: "p-6",
  }[padding];

  const variantCls =
    variant === "plain"
      ? ""
      : "rounded-card border border-subtle bg-surface shadow-card";

  return (
    <div
      className={cn(
        variantCls,
        interactive &&
          variant === "surface" &&
          "transition-all duration-200 ease-soft " +
            "hover:border-strong hover:shadow-card-hover " +
            "hover:-translate-y-[1px]",
        paddingCls,
        className,
      )}
      {...rest}
    />
  );
}

/**
 * Editorial section header — an all-caps kicker + a headline. Used both
 * inside cards and directly on the canvas for open sections. Deliberately
 * has no visual container of its own.
 */
export function SectionHeader({
  kicker,
  title,
  subtitle,
  action,
  className,
}: {
  kicker: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 md:flex-row md:items-end md:justify-between",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
          <span className="inline-block h-[6px] w-[6px] rounded-full bg-accent" />
          <span>{kicker}</span>
        </div>
        <h2 className="font-display text-display-lg text-ink-primary">
          {title}
        </h2>
        {subtitle ? (
          <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-ink-secondary">
            {subtitle}
          </p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/** Legacy in-card header for surfaces that still need a card wrapper. */
export function CardHeader({
  title,
  eyebrow,
  action,
  className,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        {eyebrow ? (
          <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-ink-muted">
            {eyebrow}
          </div>
        ) : null}
        <h3 className="text-display-md text-ink-primary truncate">{title}</h3>
      </div>
      {action}
    </div>
  );
}
