import { IconInfo } from "@/components/ui/Icon";
import { FRAMING_DISCLAIMER } from "@/lib/constants";

/**
 * Small-caps footnote at the bottom of the dashboard. Preserves the
 * exact wording from architecture §5 — never rephrased. Low visual
 * weight but always present on any page that renders framing values.
 */
export function DisclaimerFootnote() {
  return (
    <footer className="mt-16 border-t border-ink-primary/10 pt-6">
      <div className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
        <IconInfo size={12} />
        On the framing indicator
      </div>
      <p className="max-w-3xl text-[12.5px] leading-relaxed text-ink-muted">
        {FRAMING_DISCLAIMER}
      </p>
    </footer>
  );
}
