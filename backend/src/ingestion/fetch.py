"""RSS fetch + article-text extraction.

Walks each Phase-N outlet in outlets.yaml, fetches its RSS feed with
feedparser, downloads each new article with httpx, and extracts the main
body text with trafilatura. Advances rows through the state machine from
`discovered` to `extracted`.

Implemented in Week 1, step 6.
"""
