/**
 * A hand-picked set of inline SVG icons used across the shell + dashboard.
 * Sourced from the Lucide icon set (MIT) and re-drawn inline so we don't
 * pull the ~1MB icon package as a dependency.
 *
 * Every icon renders as a 1em-square <svg> and inherits `currentColor`,
 * so callers style them with the usual text-* utilities.
 */

import { forwardRef, type SVGProps } from "react";

type BaseProps = SVGProps<SVGSVGElement> & { size?: number | string };

const Base = forwardRef<SVGSVGElement, BaseProps>(function BaseIcon(
  { size = 16, strokeWidth = 1.75, ...rest }: BaseProps,
  ref,
) {
  return (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...rest}
    />
  );
});

export const IconDashboard = (p: BaseProps) => (
  <Base {...p}>
    <rect x="3"  y="3"  width="7" height="9"  rx="1.5" />
    <rect x="14" y="3"  width="7" height="5"  rx="1.5" />
    <rect x="14" y="12" width="7" height="9"  rx="1.5" />
    <rect x="3"  y="16" width="7" height="5"  rx="1.5" />
  </Base>
);

export const IconStories = (p: BaseProps) => (
  <Base {...p}>
    <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v14H6.5A2.5 2.5 0 0 0 4 19.5z" />
    <path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20" />
    <path d="M8 8h8M8 12h6" />
  </Base>
);

export const IconSearch = (p: BaseProps) => (
  <Base {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Base>
);

export const IconOutlets = (p: BaseProps) => (
  <Base {...p}>
    <path d="M3 7h13a3 3 0 0 1 3 3v9H3z" />
    <path d="M19 19V7a2 2 0 1 1 2 2v7" />
    <path d="M7 11h6M7 15h6" />
  </Base>
);

export const IconTrend = (p: BaseProps) => (
  <Base {...p}>
    <path d="M3 17 9 11l4 4 8-8" />
    <path d="M14 7h7v7" />
  </Base>
);

export const IconSpark = (p: BaseProps) => (
  <Base {...p}>
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
  </Base>
);

export const IconArrowRight = (p: BaseProps) => (
  <Base {...p}>
    <path d="M5 12h14" />
    <path d="m13 5 7 7-7 7" />
  </Base>
);

export const IconArrowUpRight = (p: BaseProps) => (
  <Base {...p}>
    <path d="M7 17 17 7" />
    <path d="M8 7h9v9" />
  </Base>
);

export const IconInfo = (p: BaseProps) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8h.01M11 12h1v5h1" />
  </Base>
);

export const IconAlert = (p: BaseProps) => (
  <Base {...p}>
    <path d="M12 3 2 20h20z" />
    <path d="M12 10v5M12 18h.01" />
  </Base>
);

export const IconCircleCheck = (p: BaseProps) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="m8 12 3 3 5-6" />
  </Base>
);

export const IconClock = (p: BaseProps) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </Base>
);

export const IconDot = (p: BaseProps) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" />
  </Base>
);

/** Hamburger — three horizontal rules. Used by the mobile TopNav. */
export const IconMenu = (p: BaseProps) => (
  <Base {...p}>
    <path d="M4 6h16M4 12h16M4 18h16" />
  </Base>
);

/** Close (×) — used by the mobile navigation sheet. */
export const IconClose = (p: BaseProps) => (
  <Base {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Base>
);

/** Sun — light mode indicator. */
export const IconSun = (p: BaseProps) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4l1.4-1.4M17 7l1.4-1.4" />
  </Base>
);

/** Moon — dark mode indicator. */
export const IconMoon = (p: BaseProps) => (
  <Base {...p}>
    <path d="M20 15.5A8 8 0 0 1 8.5 4a8 8 0 1 0 11.5 11.5z" />
  </Base>
);

/**
 * NewsLens brandmark — three lightly-overlapping lenses converging on a
 * single focal point. Same drawing as <NewsLensMark> in
 * components/brand/BrandMark.tsx but rendered at the 24-unit icon
 * grid for shell-level use.
 */
export const IconBrand = (p: BaseProps) => (
  <Base {...p} strokeWidth={1.5}>
    <circle cx="8"  cy="14" r="5.2" opacity="0.55" />
    <circle cx="16" cy="14" r="5.2" opacity="0.55" />
    <circle cx="12" cy="9"  r="5.2" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
  </Base>
);
