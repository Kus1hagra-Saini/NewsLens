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
import Trending from "@/pages/Trending";

/**
 * Router — Phase 2 editorial shell.
 *
 * `/` now renders the real NewsLens editorial homepage (Hot Now →
 * Just Updated → Discover) instead of the transitional Phase 1
 * dashboard. Every other route is unchanged. The About / Outlets /
 * Trending / Search / OutletProfile placeholders continue to render
 * "in development" pages so the site stays end-to-end navigable while
 * the corresponding phases are built out.
 */
export default function App() {
  return (
    <PageContainer>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/stories" element={<StoriesList />} />
        <Route path="/stories/:id" element={<StoryDetail />} />
        <Route path="/trending" element={<Trending />} />
        <Route path="/outlets" element={<OutletsIndex />} />
        <Route path="/outlets/:slug" element={<OutletProfile />} />
        <Route path="/search" element={<Search />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </PageContainer>
  );
}
