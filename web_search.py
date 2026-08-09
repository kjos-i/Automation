"""web_search.py - repeatable web search via Tavily, saved to disk.

Set what to search for plus optional filters (allowed/forbidden sites, a time
window, how many results, general vs news) at the top, run it, and get ranked
results plus an optional short AI summary. With TIMESTAMP_FILENAME on, each run
is saved to a dated file, so re-running the same query builds a little history.
Set REPEAT on to keep re-running the query on a fixed cycle (a simple monitor);
stop it with Ctrl+C.

Tavily is itself an LLM-powered search service, so this script adds no LLM of
its own: the search and the optional summary come straight from Tavily's API.

Setup:
    pip install tavily-python python-dotenv
    # put your key in a .env file next to this script:
    #   TAVILY_API_KEY=tvly-...
    python web_search.py
"""

# ================= CONFIG - edit these, then run =================
QUERY = "latest developments in battery recycling"

SEARCH_DEPTH = "basic"  # "basic" | "advanced"
TOPIC = "general"  # "general" | "news"
TIME_RANGE = None  # None | "day" | "week" | "month" | "year"
MAX_RESULTS = 5

INCLUDE_DOMAINS = []  # only search these sites, e.g. ["reuters.com"]
EXCLUDE_DOMAINS = []  # never these sites, e.g. ["pinterest.com"]

INCLUDE_ANSWER = True  # also get Tavily's short AI summary

SAVE_TO_FILE = False
OUTPUT_FILE = r"C:\path\to\search_results.md"  # written as Markdown; keep .md (or .txt). Used only if SAVE_TO_FILE
TIMESTAMP_FILENAME = True  # add date and time to the name (keeps a history)

REPEAT = False  # re-run automatically on a cycle (Ctrl+C to stop)
CYCLE_MINUTES = 60  # minutes between runs when REPEAT is on
# ================================================================

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from tavily import TavilyClient


def run_search(client: TavilyClient) -> dict:
    """Call Tavily with the configured filters. Only non-empty filters are
    passed, so defaults apply otherwise."""
    params = {
        "query": QUERY,
        "search_depth": SEARCH_DEPTH,
        "topic": TOPIC,
        "max_results": MAX_RESULTS,
        "include_answer": INCLUDE_ANSWER,
    }
    if TIME_RANGE:
        params["time_range"] = TIME_RANGE
    if INCLUDE_DOMAINS:
        params["include_domains"] = INCLUDE_DOMAINS
    if EXCLUDE_DOMAINS:
        params["exclude_domains"] = EXCLUDE_DOMAINS
    return client.search(**params)


def format_report(resp: dict) -> str:
    """Render the response as readable markdown (also used for the saved file)."""
    lines = [f"# Web search: {QUERY}", ""]
    answer = resp.get("answer")
    if answer:
        lines += ["## Summary", answer, ""]
    lines.append("## Results")
    lines.append("")
    for i, r in enumerate(resp.get("results", []), 1):
        title = r.get("title") or r.get("url") or "(untitled)"
        lines.append(f"{i}. [{title}]({r.get('url')})")
        meta_bits = []
        if r.get("published_date"):
            meta_bits.append(r["published_date"])
        if isinstance(r.get("score"), (int, float)):
            meta_bits.append(f"score {r['score']:.2f}")
        if meta_bits:
            lines.append(f"   {' | '.join(meta_bits)}")
        snippet = (r.get("content") or "").strip()
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")
    return "\n".join(lines)


def resolve_output_path() -> Path:
    p = Path(OUTPUT_FILE)
    if TIMESTAMP_FILENAME:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = p.with_name(f"{p.stem}_{stamp}{p.suffix}")
    return p


def do_one_run(client: TavilyClient) -> None:
    print(f"Searching: {QUERY!r}\n")
    try:
        resp = run_search(client)
    except Exception as exc:
        print(f"Search failed: {exc}", file=sys.stderr)
        return  # in a REPEAT loop, one failure should not stop the monitor
    report = format_report(resp)
    print(report)
    if SAVE_TO_FILE:
        dest = resolve_output_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(report, encoding="utf-8")
        print(f"\nSaved to {dest}")


def main() -> None:
    load_dotenv()
    if not os.getenv("TAVILY_API_KEY"):
        sys.exit(
            "No TAVILY_API_KEY found. Put it in a .env file next to this script:\n"
            "  TAVILY_API_KEY=tvly-..."
        )
    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

    if not REPEAT:
        do_one_run(client)
        return

    if SAVE_TO_FILE and not TIMESTAMP_FILENAME:
        print("(note: TIMESTAMP_FILENAME is off, so each run overwrites the same file)\n")
    print(f"REPEAT on: running every {CYCLE_MINUTES} min. Press Ctrl+C to stop.\n")
    try:
        while True:
            do_one_run(client)
            print(f"\n--- sleeping {CYCLE_MINUTES} min ---\n")
            time.sleep(CYCLE_MINUTES * 60)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
