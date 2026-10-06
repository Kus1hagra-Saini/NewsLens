import { Route, Routes } from "react-router-dom";

import { PageContainer } from "@/components/layout/PageContainer";
import About from "@/pages/About";
import Home from "@/pages/Home";
import NotFound from "@/pages/NotFound";
import OutletProfile from "@/pages/OutletProfile";
import OutletsIndex from "@/pages/OutletsIndex";
import Search from "@/pages/Search";
import StoriesList from "@/pages/StoriesList";
import StoryDetail from "@/pages/StoryDetail";

/**
 * Router — editorial shell.
 *
 * `/` renders the editorial homepage (Hot Now → Just Updated →
 * Discover). `/stories` is the full paginated list and
 * `/stories/:id` is the comparison page for one story. `/outlets`
 * is the simple directory of the 15 publications NewsLens tracks;
 * the `/outlets/:slug` placeholder is kept for routing continuity.
 * The About / Search placeholders continue to render "in development"
 * pages so the site stays end-to-end navigable while the
 * corresponding phases are built out.
 */
export default function App() {
  return (
    <PageContainer>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/stories" element={<StoriesList />} />
        <Route path="/stories/:id" element={<StoryDetail />} />
        <Route path="/outlets" element={<OutletsIndex />} />
        <Route path="/outlets/:slug" element={<OutletProfile />} />
        <Route path="/search" element={<Search />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </PageContainer>
  );
}
