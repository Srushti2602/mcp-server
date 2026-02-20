"""
MCP Web Scraper Server — Playwright Edition

An MCP (Model Context Protocol) server that exposes web scraping tools.
Claude Desktop connects to this server over stdio and can call these tools
to scrape pages, extract links, and query elements from any website.

Key concepts:
  - MCP is like "USB for AI": it standardizes how AI models call external tools.
  - FastMCP reads your function's name, type hints, and docstring to automatically
    generate the JSON Schema that Claude sees when it discovers your tools.
  - stdio transport: Claude Desktop spawns this script as a subprocess and
    communicates via JSON-RPC over stdin/stdout.
  - NEVER use print() — it would corrupt the JSON-RPC channel.
    All logging goes to stderr instead.
"""

import logging
import re
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Logging — must go to stderr so we don't interfere with the stdio JSON-RPC
# channel on stdout. This is critical for any MCP server.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("web-scraper")

# ---------------------------------------------------------------------------
# Create the MCP server instance.
# FastMCP inspects each @mcp.tool() function and auto-generates the tool's
# JSON Schema from its name, type hints, and docstring.
# ---------------------------------------------------------------------------
mcp = FastMCP(name="web-scraper")


# ---------------------------------------------------------------------------
# Helper: launch a headless browser, navigate to a URL, return parsed HTML

async def get_page(url: str, wait_time: int = 5) -> BeautifulSoup:
    """
    Launch headless Chromium, navigate to `url`, wait for JS to render,
    and return a BeautifulSoup object of the fully-rendered page.

    Why async?  Both Playwright and MCP use async/await natively, so they
    compose together without any thread hacks.

    Args:
        url: The page to fetch.
        wait_time: Extra seconds to wait after network is idle (for slow JS).
    """
    logger.info(f"Fetching: {url}")
    browser = None
    pw = None
    try:
        # async_playwright() gives us a Playwright instance we can use
        # to launch browsers.
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)

        # A "browser context" is like an incognito window — isolated cookies,
        # cache, etc.  Good practice even if we only open one page.
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # Use "domcontentloaded" first (fast, works on all sites), then
        # wait for the page to settle. Heavy SPAs like Amazon never reach
        # "networkidle" because of analytics/ads firing continuously.
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for JS frameworks to render content. SPAs (React, Angular)
        # need time after the initial HTML loads to fetch data and paint.
        await page.wait_for_timeout(wait_time * 1000)

        # Scroll down to trigger lazy-loaded content, then wait again.
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        # page.content() returns the *rendered* HTML — after JS has run.
        html = await page.content()
        logger.info(f"Got {len(html)} bytes from {url}")
        return BeautifulSoup(html, "html.parser")
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()


# ---------------------------------------------------------------------------
# Tool 1: scrape_url — fetch a page and return clean Markdown content
# ---------------------------------------------------------------------------
@mcp.tool()
async def scrape_url(url: str, wait_time: int = 5) -> str:
    """Scrape a webpage and return its main content as clean Markdown.

    Launches a headless browser to fully render the page (including JS),
    strips navigation/ads/scripts, and converts the main content to Markdown.

    Args:
        url: The full URL to scrape (e.g. "https://example.com").
        wait_time: Seconds to wait for JS rendering after network is idle.
                   Increase for slow single-page apps. Default: 3.
    """
    soup = await get_page(url, wait_time)

    # Remove noisy elements that aren't part of the main content.
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Try to find the main content area. Fall back to <body> if needed.
    content = soup.find("main") or soup.find("article") or soup.find("body")
    if not content:
        return "Error: Could not find any content on the page."

    # Convert HTML → Markdown for a clean, readable output.
    markdown = md(str(content), heading_style="ATX", strip=["img"])

    # Clean up excessive whitespace.
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = markdown.strip()

    if not markdown:
        return "Error: Page rendered but no text content was found."

    return markdown


# ---------------------------------------------------------------------------
# Tool 2: extract_links — get all links from a page
# ---------------------------------------------------------------------------
@mcp.tool()
async def extract_links(url: str, same_domain_only: bool = False) -> str:
    """Extract all links from a webpage.

    Returns a deduplicated Markdown list of links found on the page.

    Args:
        url: The full URL to scrape.
        same_domain_only: If True, only return links that point to the same
                          domain as the input URL. Useful for site mapping.
    """
    soup = await get_page(url)
    base_domain = urlparse(url).netloc
    seen = set()
    links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        # Resolve relative URLs (e.g. "/about" → "https://example.com/about").
        full_url = urljoin(url, href)

        # Skip non-HTTP links (mailto:, javascript:, tel:, etc.).
        if not full_url.startswith(("http://", "https://")):
            continue

        # Optional: only keep links on the same domain.
        if same_domain_only and urlparse(full_url).netloc != base_domain:
            continue

        # Deduplicate.
        if full_url in seen:
            continue
        seen.add(full_url)

        # Use the link text if available, otherwise use the URL itself.
        text = a_tag.get_text(strip=True) or full_url
        links.append(f"- [{text}]({full_url})")

    if not links:
        return "No links found on this page."

    header = f"Found {len(links)} links on {url}:\n\n"
    return header + "\n".join(links)


# ---------------------------------------------------------------------------
# Tool 3: search_text — find a word/phrase on a page and return matching links
# ---------------------------------------------------------------------------
@mcp.tool()
async def search_text(url: str, query: str) -> str:
    """Search for a word or phrase on a webpage.

    Finds all occurrences of the search term in the page text. For each match,
    returns the surrounding context and any associated link (URL). Useful for
    finding job listings, product names, or any text on a page.

    Args:
        url: The full URL to search.
        query: The word or phrase to search for (case-insensitive).
    """
    soup = await get_page(url)

    # Remove non-content tags.
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    query_lower = query.lower()
    results = []
    seen_urls = set()

    # Search all text-containing elements for the query.
    for element in soup.find_all(string=lambda text: text and query_lower in text.lower()):
        parent = element.parent
        if not parent:
            continue

        # Get the text of the containing block element for context.
        # Walk up to find a meaningful parent (not just a <span> or <b>).
        context_el = parent
        for _ in range(5):
            if context_el.parent and context_el.name in (
                "span", "b", "i", "em", "strong", "small", "mark"
            ):
                context_el = context_el.parent
            else:
                break

        context_text = context_el.get_text(strip=True)[:200]

        # Find the closest <a> link — either the parent itself or a nearby one.
        link_tag = parent.find_parent("a", href=True) or context_el.find("a", href=True)
        link_url = None
        if link_tag and link_tag.get("href"):
            link_url = urljoin(url, link_tag["href"])
            if not link_url.startswith(("http://", "https://")):
                link_url = None

        # Deduplicate by URL (or by context text if no URL).
        dedup_key = link_url or context_text
        if dedup_key in seen_urls:
            continue
        seen_urls.add(dedup_key)

        if link_url:
            results.append(f"- **{context_text}**\n  Link: {link_url}")
        else:
            results.append(f"- {context_text}")

    if not results:
        return f'Not found: "{query}" does not appear on {url}'

    header = f'Found {len(results)} matches for "{query}" on {url}:\n\n'
    return header + "\n\n".join(results)


# ---------------------------------------------------------------------------
# Tool 3: extract_elements — query elements by CSS selector
# ---------------------------------------------------------------------------
@mcp.tool()
async def extract_elements(url: str, css_selector: str, limit: int = 20) -> str:
    """Extract specific elements from a webpage using a CSS selector.

    Useful for pulling structured data like headings, list items, table rows,
    prices, or any repeated element pattern.

    CSS selector examples:
      - "h2"              → all <h2> headings
      - ".price"          → elements with class="price"
      - "#main-content p" → paragraphs inside #main-content
      - "table tr"        → all table rows
      - "a[href*=pdf]"    → links containing "pdf" in the href

    Args:
        url: The full URL to scrape.
        css_selector: A CSS selector to match elements.
        limit: Maximum number of elements to return (default 20).
    """
    soup = await get_page(url)
    elements = soup.select(css_selector)

    if not elements:
        return f'No elements found matching "{css_selector}" on {url}.'

    results = []
    for i, el in enumerate(elements[:limit]):
        # Gather useful attributes (id, class, href) for context.
        attrs = []
        if el.get("id"):
            attrs.append(f'id="{el["id"]}"')
        if el.get("class"):
            attrs.append(f'class="{" ".join(el["class"])}"')
        if el.get("href"):
            attrs.append(f'href="{el["href"]}"')

        attr_str = f" ({', '.join(attrs)})" if attrs else ""
        text = el.get_text(strip=True)

        results.append(f"{i + 1}. <{el.name}{attr_str}>: {text}")

    header = (
        f'Found {len(elements)} elements matching "{css_selector}" '
        f"(showing {min(limit, len(elements))}):\n\n"
    )
    return header + "\n".join(results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    """Start the MCP server using stdio transport.

    stdio transport means Claude Desktop will:
      1. Spawn this script as a subprocess
      2. Send JSON-RPC requests on stdin
      3. Read JSON-RPC responses from stdout
    """
    logger.info("Starting web-scraper MCP server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
