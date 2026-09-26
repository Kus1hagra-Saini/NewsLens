import { cn } from "@/lib/cn";
import { useTheme } from "@/lib/theme";
import { IconMoon, IconSun } from "@/components/ui/Icon";

/**
 * Two-state light/dark toggle for the top nav.
 *
 * Shows the icon of the theme the click will switch INTO (sun when
 * currently dark, moon when currently light) — matches OS-level
 * toggles and reads as "click for X". Persists across sessions via
 * ``useTheme`` and syncs across tabs. Falls back to auto when the
 * user has never touched it (see the preflight script in
 * ``index.html``).
 */
export function ThemeToggle({
  className,
  variant = "quiet",
}: {
  className?: string;
  /**
   * "quiet"  — small square icon button (top nav desktop + mobile).
   * "labeled" — icon + label pill (mobile sheet or About page).
   */
  variant?: "quiet" | "labeled";
}) {
  const { resolved, toggle } = useTheme();
  const nextIsDark = resolved === "light";
  const label = nextIsDark ? "Switch to dark mode" : "Switch to light mode";
  const nextLabel = nextIsDark ? "Dark" : "Light";

  if (variant === "labeled") {
    return (
      <button
        type="button"
        onClick={toggle}
        aria-label={label}
        title={label}
        className={cn(
          "inline-flex items-center gap-2 rounded-full",
          "border border-subtle px-3 py-1.5",
          "text-[11.5px] font-semibold uppercase tracking-[0.12em] text-ink-primary",
          "transition-colors hover:border-strong hover:bg-surface-alt",
          className,
        )}
      >
        {nextIsDark ? <IconMoon size={13} /> : <IconSun size={13} />}
        {nextLabel}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className={cn(
        "grid h-8 w-8 place-items-center rounded-md",
        "text-ink-muted hover:text-ink-primary hover:bg-surface-alt",
        "transition-colors",
        className,
      )}
    >
      {nextIsDark ? <IconMoon size={16} /> : <IconSun size={16} />}
    </button>
  );
}
