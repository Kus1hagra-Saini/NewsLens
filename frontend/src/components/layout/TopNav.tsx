import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { BrandMark } from "@/components/brand/BrandMark";
import { IconMenu, IconSearch } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { BRAND_TAGLINE } from "@/lib/constants";
import { MobileNavSheet } from "./MobileNavSheet";
import { ThemeToggle } from "./ThemeToggle";

/** Primary navigation entry — shared by the desktop nav and the mobile sheet. */
export interface NavEntry {
  to: string;
  label: string;
  end?: boolean;
}

export const PRIMARY_NAV: NavEntry[] = [
  { to: "/",         label: "Home",     end: true },
  { to: "/stories",  label: "Stories" },
  { to: "/outlets",  label: "Outlets" },
];

/**
 * Publication-style top navigation.
 *
 * Desktop (lg+):  Two-row masthead. Top row is brand + product
 *                 tagline on the left, quiet secondary controls
 *                 (search icon, About link) on the right, separated
 *                 from the primary nav row by a hairline. Active
 *                 primary link gets a 2px accent underline that sits
 *                 on the header's own bottom hairline so the two
 *                 rules visually connect.
 *
 * Mobile (<lg):   Sticky top strip with the wordmark on the left and
 *                 a menu button on the right; the button opens the
 *                 <MobileNavSheet /> — a right-anchored full-height
 *                 sheet with the same primary nav plus About and a
 *                 tiny disclaimer footer.
 *
 * Nothing here reads from the API. The live-pipeline tile that used
 * to live at the bottom of the old sidebar is intentionally NOT here
 * — it will move to /about (Phase 4). The reader should not see
 * internal telemetry on every page.
 */
export function TopNav() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const location = useLocation();

  // Any route change closes the sheet — belt-and-braces alongside
  // each NavLink's onClick handler.
  useEffect(() => {
    setSheetOpen(false);
  }, [location.pathname]);

  return (
    <>
      <header
        className={cn(
          "sticky top-0 z-30",
          "bg-surface/85 supports-[backdrop-filter]:bg-surface/65",
          "backdrop-blur border-b border-ink-primary/10",
        )}
      >
        {/* ─────────────  DESKTOP (lg+)  ───────────── */}
        <div className="hidden lg:block mx-auto w-full max-w-[1240px] px-10 lg:px-14">
          <div className="flex items-baseline justify-between pt-5">
            <div className="flex items-baseline gap-4">
              <BrandMark />
              <span className="hidden xl:inline text-[12.5px] italic text-ink-muted">
                {BRAND_TAGLINE}
              </span>
            </div>
            <div className="flex items-center gap-4">
              <Link
                to="/search"
                aria-label="Search"
                className={cn(
                  "grid h-8 w-8 place-items-center rounded-md",
                  "text-ink-muted hover:text-ink-primary hover:bg-surface-alt",
                  "transition-colors",
                )}
              >
                <IconSearch size={16} />
              </Link>
              <ThemeToggle />
              <NavLink
                to="/about"
                className={({ isActive }) =>
                  cn(
                    "text-[11px] font-semibold uppercase tracking-[0.14em]",
                    "transition-colors",
                    isActive
                      ? "text-accent"
                      : "text-ink-muted hover:text-ink-primary",
                  )
                }
              >
                About
              </NavLink>
            </div>
          </div>

          <div className="mt-4 border-t border-ink-primary/10" />

          <nav className="flex items-center gap-8">
            {PRIMARY_NAV.map((entry) => (
              <NavLink
                key={entry.to}
                to={entry.to}
                end={entry.end}
                className={({ isActive }) =>
                  cn(
                    "relative pt-4 pb-4 -mb-[1px] border-b-2",
                    "text-[12px] font-semibold uppercase tracking-[0.16em]",
                    "transition-colors duration-150 ease-editorial",
                    isActive
                      ? "border-accent text-ink-primary"
                      : "border-transparent text-ink-secondary hover:text-ink-primary",
                  )
                }
              >
                {entry.label}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* ─────────────  MOBILE (<lg)  ───────────── */}
        <div className="lg:hidden flex items-center justify-between px-5 py-3.5">
          <BrandMark />
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <button
              type="button"
              onClick={() => setSheetOpen(true)}
              aria-label="Open menu"
              aria-expanded={sheetOpen}
              className={cn(
                "grid h-9 w-9 place-items-center rounded-md",
                "text-ink-primary hover:bg-surface-alt transition-colors",
              )}
            >
              <IconMenu size={18} />
            </button>
          </div>
        </div>
      </header>

      <MobileNavSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        entries={PRIMARY_NAV}
      />
    </>
  );
}
