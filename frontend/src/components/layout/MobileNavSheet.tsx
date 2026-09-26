import { useEffect } from "react";
import { Link, NavLink } from "react-router-dom";

import { BrandMark } from "@/components/brand/BrandMark";
import { IconClose, IconSearch } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { BRAND_TAGLINE, FRAMING_DISCLAIMER } from "@/lib/constants";
import type { NavEntry } from "./TopNav";

/**
 * Full-height right-anchored navigation sheet for mobile viewports.
 *
 * Opens over the current page with a canvas-tinted backdrop; body
 * scroll is locked while open, and Escape closes it. Primary nav
 * items are set in Fraunces at reading size so the sheet reads as a
 * publication table of contents rather than an app drawer of icon
 * buttons. About sits below the primary nav; a very small
 * framing-indicator disclaimer anchors the bottom.
 *
 * The sheet mounts unconditionally and uses opacity / translate for
 * its open state — this keeps focus + transitions well-behaved and
 * avoids remounting nav items on every open.
 */
export function MobileNavSheet({
  open,
  onClose,
  entries,
}: {
  open: boolean;
  onClose: () => void;
  entries: NavEntry[];
}) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  return (
    <div
      aria-hidden={!open}
      className={cn(
        "lg:hidden fixed inset-0 z-40",
        "transition-opacity duration-200 ease-editorial",
        open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
      )}
    >
      {/* Backdrop — clicking closes the sheet. */}
      <button
        type="button"
        onClick={onClose}
        aria-label="Close menu"
        tabIndex={open ? 0 : -1}
        className="absolute inset-0 bg-canvas/70 backdrop-blur-sm"
      />

      {/* Sheet panel */}
      <div
        className={cn(
          "absolute right-0 top-0 h-full w-[min(360px,88vw)]",
          "bg-canvas border-l border-ink-primary/10",
          "flex flex-col",
          "transition-transform duration-[250ms] ease-editorial",
          open ? "translate-x-0" : "translate-x-full",
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Site navigation"
      >
        <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-ink-primary/10">
          <BrandMark onClick={onClose} />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            className={cn(
              "grid h-9 w-9 place-items-center rounded-md",
              "text-ink-primary hover:bg-surface-alt transition-colors",
            )}
          >
            <IconClose size={18} />
          </button>
        </div>

        {/* Search shortcut */}
        <Link
          to="/search"
          onClick={onClose}
          className={cn(
            "mx-5 mt-5 flex items-center gap-2.5 rounded-md px-3 py-2.5",
            "border border-ink-primary/10 bg-surface-alt/60",
            "text-[13.5px] text-ink-muted",
            "hover:text-ink-primary hover:border-ink-primary/25 transition-colors",
          )}
        >
          <IconSearch size={15} />
          Search stories &amp; articles
        </Link>

        {/* Primary nav — Fraunces, big, table-of-contents feel */}
        <nav className="mt-6 px-5 flex flex-col">
          {entries.map((entry) => (
            <NavLink
              key={entry.to}
              to={entry.to}
              end={entry.end}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  "font-display text-display-md py-3",
                  "border-b border-ink-primary/10",
                  "transition-colors",
                  isActive
                    ? "text-accent"
                    : "text-ink-primary hover:text-accent",
                )
              }
            >
              {entry.label}
            </NavLink>
          ))}

          <NavLink
            to="/about"
            onClick={onClose}
            className={({ isActive }) =>
              cn(
                "mt-6 text-[11.5px] font-semibold uppercase tracking-[0.16em]",
                "transition-colors",
                isActive
                  ? "text-accent"
                  : "text-ink-muted hover:text-ink-primary",
              )
            }
          >
            About &amp; methodology →
          </NavLink>
        </nav>

        <div className="mt-auto px-5 pb-6 pt-6 border-t border-ink-primary/10">
          <p className="text-[11px] italic leading-relaxed text-ink-muted">
            {BRAND_TAGLINE}
          </p>
          <p className="mt-2 text-[10px] leading-relaxed text-ink-muted/80">
            {FRAMING_DISCLAIMER}
          </p>
        </div>
      </div>
    </div>
  );
}
