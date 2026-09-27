import { Navigate, Route, Routes } from "react-router-dom";

import { PageContainer } from "@/components/layout/PageContainer";
import About from "@/pages/About";
import Home from "@/pages/Home";
import NotFound from "@/pages/NotFound";
import OutletProfile from "@/pages/OutletProfile";
import OutletsIndex from "@/pages/OutletsIndex";
import PositiveStories from "@/pages/PositiveStories";
import Search from "@/pages/Search";
import StoriesList from "@/pages/StoriesList";
import StoryDetail from "@/pages/StoryDetail";

/**
 * Router — Phase 2 editorial shell.
 *
 * `/` renders the editorial homepage (Hot Now → Just Updated →
 * Discover). ``/positive`` renders Positive Stories — the deterministic
 * feed of stories whose cross-outlet coverage has been predominantly
 * positive (see ``pages/PositiveStories.tsx``); this replaces the old
 * ``/trending`` placeholder, which never had a live backend. ``/trending``
 * continues to resolve — as a redirect to ``/positive`` — so any external
 * link to the old path lands on the new experience rather than a 404.
 *
 * The About / Outlets / Search / OutletProfile placeholders continue to
 * render "in development" pages so the site stays end-to-end navigable
 * while the corresponding phases are built out.
 */
export default function App() {
  return (
    <PageContainer>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/stories" element={<StoriesList />} />
        <Route path="/stories/:id" element={<StoryDetail />} />
        <Route path="/positive" element={<PositiveStories />} />
        {/* Legacy path — redirect to the replacement experience so no
            bookmarks or in-flight links break. */}
        <Route path="/trending" element={<Navigate to="/positive" replace />} />
        <Route path="/outlets" element={<OutletsIndex />} />
        <Route path="/outlets/:slug" element={<OutletProfile />} />
        <Route path="/search" element={<Search />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </PageContainer>
  );
}
