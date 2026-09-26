import { Link } from "react-router-dom";
import type { SVGProps } from "react";
import { BRAND_NAME } from "@/lib/constants";
import { cn } from "@/lib/cn";

/**
 * NewsLens mark — three lightly-overlapping lenses converging on a
 * single focal point. Conceptually: "multiple perspectives on one
 * story." Reads at 16px, holds up at 64px+.
 *
 * The mark is a single ~1KB inline SVG so it never hits the network
 * and inherits `currentColor` from the surrounding text — the
 * <BrandMark> component tints it with the accent colour, and the
 * on-dark variant on the masthead uses it in white.
 *
 * Moved from components/shell/ in the editorial redesign — the
 * publication top nav is chrome that belongs alongside the brand,
 * not the (now removed) permanent sidebar shell.
 */
export function NewsLensMark({
  size = 20,
  className,
  ...rest
}: SVGProps<SVGSVGElement> & { size?: number | string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 32"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      <circle cx="11" cy="18" r="7" opacity="0.55" />
      <circle cx="21" cy="18" r="7" opacity="0.55" />
      <circle cx="16" cy="11" r="7" />
      <circle cx="16" cy="16" r="1.9" fill="currentColor" stroke="none" />
    </svg>
  );
}

/**
 * Compact brand — the mark + a wordmark set in the display serif.
 * `variant="light"` uses the accent tint on the mark; `variant="onDark"`
 * flips both to a solid white for a hypothetical dark masthead strip.
 *
 * The product tagline is deliberately NOT rendered inside BrandMark
 * itself — the top navigation places it separately so it can be
 * hidden at narrower viewports without changing the brand mark.
 */
export function BrandMark({
  className,
  variant = "light",
  onClick,
}: {
  className?: string;
  variant?: "light" | "onDark";
  onClick?: () => void;
}) {
  const onDark = variant === "onDark";
  return (
    <Link
      to="/"
      onClick={onClick}
      className={cn(
        "group inline-flex items-center gap-2.5 rounded-md py-0.5",
        "outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
        className,
      )}
    >
      <NewsLensMark
        size={26}
        className={cn(
          "transition-transform duration-300 ease-editorial",
          "group-hover:rotate-[-6deg]",
          onDark ? "text-white" : "text-accent",
        )}
      />
      <span
        className={cn(
          "font-display text-[19px] font-semibold leading-none tracking-[-0.02em]",
          onDark ? "text-white" : "text-ink-primary",
        )}
      >
        {BRAND_NAME}
      </span>
    </Link>
  );
}
