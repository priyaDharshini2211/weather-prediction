"""Web fallback for GENERAL knowledge only (never used to look up facts about the document's owner)."""
import logging

logger = logging.getLogger(__name__)

# Individual search engines frequently block or rate-limit scrapers, so try several until one answers.
BACKENDS = ("yahoo", "duckduckgo", "brave", "bing", "mojeek", "google")


def _is_ad(url: str) -> bool:
    """Sponsored results come back as tracking redirects (e.g. bing.com/aclick); never present them as sources."""
    return "/aclick" in url or "doubleclick.net" in url or "googleadservices.com" in url


def search_web(query: str, max_results: int = 4) -> list[dict]:
    """Returns [{title, url, snippet}]. Returns [] if every engine fails so the agent degrades gracefully."""
    try:
        from ddgs import DDGS
    except ImportError:
        logger.warning("ddgs is not installed; web fallback disabled")
        return []

    for backend in BACKENDS:
        try:
            results = DDGS().text(query, max_results=max_results, backend=backend)
        except Exception as error:  # "No results found", timeouts, rate limits...
            logger.info("Web search backend %s failed: %s", backend, error)
            continue
        items = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": (r.get("body") or "")[:300]}
            for r in results
            if r.get("href") and not _is_ad(r["href"])
        ]
        if items:
            return items
    logger.warning("All web search backends failed for %r", query)
    return []
