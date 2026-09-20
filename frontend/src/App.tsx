import { Route, Routes, Link } from "react-router-dom";
import Home from "./pages/Home";
import StoryDetail from "./pages/StoryDetail";
import OutletProfile from "./pages/OutletProfile";
import Trends from "./pages/Trends";
import Search from "./pages/Search";
import Eval from "./pages/Eval";

// Routes mirror architecture §11: / /story/:id /outlet/:slug /trends /search /eval.
// Page bodies are placeholders during Week 1; they land in Weeks 3–4.
export default function App() {
  return (
    <div className="app">
      <nav className="app-nav">
        <Link to="/">NewsLens</Link>
        <Link to="/trends">Trends</Link>
        <Link to="/search">Search</Link>
        <Link to="/eval">Eval</Link>
      </nav>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/story/:id" element={<StoryDetail />} />
          <Route path="/outlet/:slug" element={<OutletProfile />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/search" element={<Search />} />
          <Route path="/eval" element={<Eval />} />
        </Routes>
      </main>
    </div>
  );
}
