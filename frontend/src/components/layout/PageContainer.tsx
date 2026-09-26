import type { ReactNode } from "react";

import { Footer } from "./Footer";
import { TopNav } from "./TopNav";

/**
 * Top-level application chrome — publication style.
 *
 *   [ TopNav (sticky) ]
 *   [ main, mx-auto max-w-[1240px] editorial gutters ]
 *   [ Footer ]
 *
 * The old flex-row shell (permanent sidebar + main scroll column) is
 * gone. Reading flow is strictly vertical, which is the shape modern
 * digital news publications use.
 */
export function PageContainer({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-canvas text-ink-primary">
      <TopNav />
      <main className="flex-1">
        <div className="mx-auto w-full max-w-[1240px] px-5 py-8 md:px-10 md:py-12 lg:px-14 lg:py-14">
          {children}
        </div>
      </main>
      <Footer />
    </div>
  );
}
