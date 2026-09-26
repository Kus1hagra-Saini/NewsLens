import type { Config } from "tailwindcss";

/**
 * NewsLens — editorial design tokens.
 *
 * The palette is deliberately small: one editorial accent (coral-red),
 * three framing semantics (critical / neutral / supportive), and neutral
 * warm surfaces. All hues use CSS variables so light + dark themes stay
 * in one place (see src/styles/index.css).
 *
 * Typography is a two-face system:
 *   - `font-display` (Fraunces variable) for major headlines only
 *   - `font-sans`   (Inter variable) for everything else
 *   - `font-mono`   (JetBrains Mono) for occasional data blocks
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        canvas:           "rgb(var(--color-canvas) / <alpha-value>)",
        surface:          "rgb(var(--color-surface) / <alpha-value>)",
        "surface-alt":    "rgb(var(--color-surface-alt) / <alpha-value>)",
        "surface-inset":  "rgb(var(--color-surface-inset) / <alpha-value>)",
        subtle:           "rgb(var(--color-border-subtle) / <alpha-value>)",
        strong:           "rgb(var(--color-border-strong) / <alpha-value>)",
        hairline:         "rgb(var(--color-hairline) / <alpha-value>)",
        ink: {
          primary:    "rgb(var(--color-ink-primary) / <alpha-value>)",
          secondary:  "rgb(var(--color-ink-secondary) / <alpha-value>)",
          muted:      "rgb(var(--color-ink-muted) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          strong:  "rgb(var(--color-accent-strong) / <alpha-value>)",
          soft:    "rgb(var(--color-accent-soft) / <alpha-value>)",
          ink:     "rgb(var(--color-accent-ink) / <alpha-value>)",
        },
        framing: {
          critical:          "rgb(var(--color-framing-critical) / <alpha-value>)",
          "critical-tint":   "rgb(var(--color-framing-critical-tint) / <alpha-value>)",
          neutral:           "rgb(var(--color-framing-neutral) / <alpha-value>)",
          "neutral-tint":    "rgb(var(--color-framing-neutral-tint) / <alpha-value>)",
          supportive:        "rgb(var(--color-framing-supportive) / <alpha-value>)",
          "supportive-tint": "rgb(var(--color-framing-supportive-tint) / <alpha-value>)",
        },
      },
      fontFamily: {
        display: [
          "Fraunces",
          "ui-serif",
          "Georgia",
          "Cambria",
          "Times New Roman",
          "serif",
        ],
        sans: [
          "InterVariable",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      fontSize: {
        // Editorial display scale — the front-page headline treatment.
        // `display-3xl` is added in the Phase 1 shell to prepare the
        // Phase 2 homepage hot-now hero headline; not yet used in any
        // page.
        "display-3xl": ["4.5rem",  { lineHeight: "1.02", letterSpacing: "-0.03em",  fontWeight: "600" }],
        "display-2xl": ["3.75rem", { lineHeight: "1.04", letterSpacing: "-0.025em", fontWeight: "600" }],
        "display-xl":  ["2.75rem", { lineHeight: "1.08", letterSpacing: "-0.02em",  fontWeight: "600" }],
        "display-lg":  ["1.875rem", { lineHeight: "1.15", letterSpacing: "-0.015em", fontWeight: "600" }],
        "display-md":  ["1.375rem", { lineHeight: "1.25", letterSpacing: "-0.01em",  fontWeight: "600" }],
        // KPI numerals — large, tight, tabular.
        kpi:           ["2.75rem", { lineHeight: "1.02", letterSpacing: "-0.03em",  fontWeight: "600" }],
        "kpi-sm":      ["1.75rem", { lineHeight: "1.04", letterSpacing: "-0.02em",  fontWeight: "600" }],
      },
      boxShadow: {
        card:      "0 1px 2px 0 rgb(0 0 0 / 0.04)",
        "card-hover": "0 3px 12px -2px rgb(0 0 0 / 0.08)",
        pop:       "0 8px 24px -8px rgb(0 0 0 / 0.16)",
        ring:      "0 0 0 4px rgb(var(--color-accent) / 0.12)",
      },
      borderRadius: {
        DEFAULT: "0.5rem",
        card: "0.75rem",
        pill: "9999px",
      },
      transitionTimingFunction: {
        soft: "cubic-bezier(0.32, 0.72, 0, 1)",
        editorial: "cubic-bezier(0.22, 0.61, 0.36, 1)",
      },
      keyframes: {
        "fade-in": {
          "0%":   { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.55" },
        },
        "pulse-dot": {
          "0%, 100%": { transform: "scale(1)",   opacity: "1" },
          "50%":      { transform: "scale(1.4)", opacity: "0.4" },
        },
      },
      animation: {
        "fade-in":    "fade-in 260ms cubic-bezier(0.32, 0.72, 0, 1) both",
        "pulse-soft": "pulse-soft 1.8s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "pulse-dot":  "pulse-dot 2.2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
