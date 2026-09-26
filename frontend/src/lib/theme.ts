/**
 * Theme system — light / dark / auto.
 *
 * "auto" means "follow the OS via prefers-color-scheme"; it is the
 * default when no explicit choice has been persisted. "light" and
 * "dark" are explicit overrides that beat the OS preference, kept in
 * ``localStorage`` under ``STORAGE_KEY`` and applied to <html> as
 * ``data-theme="light"|"dark"`` (or the attribute is removed for
 * auto). The preflight script in ``index.html`` runs first so the
 * first paint uses the correct theme.
 *
 * Everything here is defensive: storage access is wrapped in
 * try/catch (private windows and site-data blocks can throw), and the
 * hook always renders a stable initial value even when neither
 * storage nor ``matchMedia`` is available.
 */

import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "auto";

export type ResolvedTheme = "light" | "dark";

export const STORAGE_KEY = "newslens.theme";

// ---------------------------------------------------------------------------
// Low-level DOM / storage helpers — safe to call during SSR (no-op) and
// safe to call from anywhere React lifecycle.
// ---------------------------------------------------------------------------

export function readStoredTheme(): ThemeChoice {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    /* private window / site-data blocked */
  }
  return "auto";
}

function writeStoredTheme(choice: ThemeChoice): void {
  try {
    if (choice === "auto") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, choice);
    }
  } catch {
    /* ignore */
  }
}

function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "auto") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", choice);
  }
}

function prefersDark(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

/**
 * The theme that will actually be rendered right now, given a stored
 * choice. When the choice is "auto", we peek at the OS preference; the
 * page's actual paint is driven by CSS (`prefers-color-scheme`), this
 * helper just tells UI code which glyph or label to show.
 */
export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  if (choice === "light" || choice === "dark") return choice;
  return prefersDark() ? "dark" : "light";
}

// ---------------------------------------------------------------------------
// React hook
// ---------------------------------------------------------------------------

export interface UseThemeResult {
  /** The persisted user choice — "light" | "dark" | "auto". */
  choice: ThemeChoice;
  /** The theme currently being rendered — "light" | "dark". */
  resolved: ResolvedTheme;
  /** Persist a new choice and apply it immediately. */
  setChoice: (next: ThemeChoice) => void;
  /**
   * Convenience toggle for the two-state button in the top nav.
   * Cycles light → dark → light. If the user's persisted choice is
   * "auto", the first toggle picks the OPPOSITE of the currently-
   * rendered theme (so clicking once always changes what you see).
   */
  toggle: () => void;
}

/**
 * Reactive theme state. Re-renders on:
 *   - manual changes via ``setChoice`` / ``toggle``
 *   - OS theme changes while the user's choice is "auto"
 *   - cross-tab ``storage`` events (another tab flipped the toggle)
 */
export function useTheme(): UseThemeResult {
  const [choice, setChoiceState] = useState<ThemeChoice>(() => readStoredTheme());
  const [systemDark, setSystemDark] = useState<boolean>(() => prefersDark());

  // Keep systemDark in sync with the OS preference. This lets the
  // rendered theme flip live when the user is on "auto".
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    // Older Safari uses addListener/removeListener.
    if (mq.addEventListener) {
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    } else if ((mq as unknown as { addListener: (h: (e: MediaQueryListEvent) => void) => void }).addListener) {
      const legacy = mq as unknown as {
        addListener: (h: (e: MediaQueryListEvent) => void) => void;
        removeListener: (h: (e: MediaQueryListEvent) => void) => void;
      };
      legacy.addListener(handler);
      return () => legacy.removeListener(handler);
    }
    return;
  }, []);

  // Cross-tab sync: another tab flipped the toggle → mirror it here.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return;
      const next = readStoredTheme();
      setChoiceState(next);
      applyTheme(next);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setChoice = useCallback((next: ThemeChoice) => {
    writeStoredTheme(next);
    applyTheme(next);
    setChoiceState(next);
  }, []);

  const resolved: ResolvedTheme =
    choice === "light" ? "light" :
    choice === "dark"  ? "dark" :
    (systemDark ? "dark" : "light");

  const toggle = useCallback(() => {
    // Two-state button: always flip the theme the user currently sees,
    // and persist that as an explicit choice (leaving "auto" behind).
    const currentlyDark = choice === "dark" ||
      (choice === "auto" && systemDark);
    const next: ThemeChoice = currentlyDark ? "light" : "dark";
    writeStoredTheme(next);
    applyTheme(next);
    setChoiceState(next);
  }, [choice, systemDark]);

  return { choice, resolved, setChoice, toggle };
}
