# MCP Web Scraper Server (Playwright)

A  MCP server that gives user the ability to scrape web pages, extract links, and query elements — all powered by a headless browser.

<img width="1470" height="956" alt="image" src="https://github.com/user-attachments/assets/fc7f3baf-525d-46fb-9ec3-5acc4f14eae5" />
<img width="1470" height="956" alt="image" src="https://github.com/user-attachments/assets/5a57c66d-c80b-41e4-8806-f49db3c01d6d" />



## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Install the Chromium browser for Playwright (~150MB download)
uv run playwright install chromium
```

## Claude Desktop Configuration

Add this to your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "web-scraper": {
      "command": "uv",
      "args": ["--directory", "/Users/srushtijagtap/Desktop/MCP_project", "run", "server.py"]
    }
  }
}
```

**After saving, fully restart Claude Desktop** (Cmd+Q, then reopen).

## Tools

This server exposes three tools:

| Tool | Description |
|---|---|
| `scrape_url` | Fetch a page with a headless browser and return clean Markdown |
| `extract_links` | Get all links from a page (with optional same-domain filter) |
| `extract_elements` | Query elements by CSS selector (e.g. all `h2` headings) |

## Test Prompts

Try these in Claude Desktop after setup:

- "Scrape https://example.com and summarize it"
- "What links are on python.org?"
- "Extract all h2 headings from https://news.ycombinator.com"
- "Get all links from https://docs.python.org that stay on the same domain"

## Development

### Test with the MCP Inspector

The MCP SDK includes a dev inspector — a web UI where you can call your tools interactively:

```bash
uv run mcp dev server.py
```

This opens a browser UI where you can select a tool, fill in parameters, and see the result.

### Run directly

```bash
uv run server.py
```

The server starts and waits for JSON-RPC messages on stdin. You won't see output (it goes to stderr). Press Ctrl+C to stop.

## MCP Concepts

| Concept | What it means |
|---|---|
| **MCP** | Model Context Protocol — a standard for AI ↔ tool communication ("USB for AI") |
| **Tool** | A function the AI can call. FastMCP auto-generates the schema from your Python function's name, type hints, and docstring |
| **stdio transport** | Claude Desktop spawns the server as a subprocess and talks over stdin/stdout using JSON-RPC |
| **FastMCP** | High-level Python API that handles all the protocol boilerplate |

## Project Structure

```
MCP_project/
├── server.py          # The MCP server (all tools defined here)
├── pyproject.toml     # Dependencies managed by uv
├── README.md          # This file
└── .venv/             # Virtual environment (created by uv)
```
