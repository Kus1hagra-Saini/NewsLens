import { Link } from "react-router-dom";

import { NewsLensMark } from "@/components/brand/BrandMark";
import { BRAND_NAME, FRAMING_DISCLAIMER } from "@/lib/constants";

/**
 * Compact editorial footer. Reads as a masthead footnote strip, not
 * a marketing site-map. Framing-indicator disclaimer is rendered
 * verbatim; a small About link and the current year sit on the
 * right.
 */
export function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="mt-16 border-t border-ink-primary/10">
      <div className="mx-auto w-full max-w-[1240px] px-5 py-8 md:px-10 md:py-10 lg:px-14 lg:py-12">
        <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
          <div className="max-w-xl">
            <div className="flex items-center gap-2 text-ink-primary">
              <NewsLensMark size={18} className="text-accent" />
              <span className="font-display text-[15px] font-semibold tracking-[-0.01em]">
                {BRAND_NAME}
              </span>
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-ink-muted">
              {FRAMING_DISCLAIMER}
            </p>
          </div>
          <div className="flex flex-col gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted md:items-end">
            <Link
              to="/about"
              className="hover:text-ink-primary transition-colors"
            >
              About &amp; methodology
            </Link>
            <span className="tabular">© {year} · {BRAND_NAME}</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
