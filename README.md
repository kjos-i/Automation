# Automation

Small, single-purpose scripts that take a prompt, decide what to do, and do it,
so I don't have to. Each script uses the simplest approach that fits the task:
a single LLM call, a graph, or a full agent. The right tool for the job, not one
pattern forced onto every problem. Each script's section also notes when a
browser chatbot would have done the job, and why the script earns its place:
scale (batching hundreds of items), repeatability (one command, re-run anytime),
saving results to disk, and acting on your own files.

**Author:** Ingrid Kjos ([ORCID 0000-0002-9166-3074](https://orcid.org/0000-0002-9166-3074))

## Scripts

| Script | Does | Approach |
|--------|------|----------|
| [doc_finder.py](#doc_finderpy) | semantic search over a folder of documents | single LLM call |
| [mail_finder.py](#mail_finderpy) | semantic search over an exported mailbox | single LLM call |
| [web_search.py](#web_searchpy) | repeatable web search via Tavily, saved to disk | search API (Tavily) |
| [web_search_agent.py](#web_search_agentpy) | answers a question, deciding whether and how often to web-search | ReAct agent (LangGraph) |

<!--
Per-script sections go below, alphabetical by filename (matching GitHub's
file list). Each section's heading is just the script name so the table
link anchors stay clean, e.g. [foo.py](#foopy) jumps to `### foo.py`.
-->

### doc_finder.py

**Problem:** You have a folder full of documents and want the ones about a
given topic, without opening each file to check.

**Solution:** The document counterpart to `mail_finder.py`. Write the topic in
plain language (`QUERY`), point it at a folder (`DOCS_FOLDER`, optionally
recursive), and it reads each file and asks an LLM whether it matches,
semantically. Reads `.txt` and `.md` out of the box; add `.pdf` or `.docx` to
`FILE_TYPES` and it uses `pypdf` / `python-docx` if installed (and tells you to
install them if not). Matches print to the terminal, and can optionally be
copied into a folder or written to a list file. The Anthropic key lives in a
local `.env`.

**Why this approach:** Same reasoning as `mail_finder.py`: a per-file yes/no
judgement is a single LLM call, not an agent. Built on Anthropic (Claude Haiku)
to show the same pattern on a different provider.

**Why not just ChatGPT?** A browser chat can't read a folder of hundreds of
files at once, can't copy the matches back into a folder for you, and would mean
pasting each document by hand. The script batches them in one command, acts on
your actual files, and sends only the fields you choose (one file at a time)
rather than pasting whole documents into a consumer chat.

Run:

    pip install anthropic python-dotenv     # + pypdf / python-docx for those formats
    # .env next to the script:  ANTHROPIC_API_KEY=sk-ant-...
    python doc_finder.py

### mail_finder.py

**Problem:** A friend wanted to run through all her emails and pull out the
ones about a given topic, without reading every message by hand.

**Solution:** A one-page script. You write what you are looking for in plain
language at the top (`QUERY`), point it at an exported mailbox (a `.mbox` file,
a folder of `.eml` files, or a Maildir, auto-detected), and it reads each email
and asks an LLM whether it matches. Matching is semantic, so "holidays" also
catches vacation, days off, PTO, and so on. Matches print to the terminal, and
can optionally be copied out as `.eml` files or written to a list file, all
controlled by flags at the top of the file. The OpenAI key lives in a local
`.env`, never in the script.

**Why this approach:** The task is a per-email yes/no judgement, so it is a
single LLM call per message. No agent and no tools (that would be overkill);
the model does the "understand synonyms" work for free.

**Why not just ChatGPT?** You can't paste a whole mailbox into a chat box. The
script scans the entire export in one command, saves the matches to disk (`.eml`
files plus a list), and sends only the fields you choose, one email at a time,
instead of pasting private mail into a consumer chat.

Run:

    pip install openai python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...
    python mail_finder.py

### web_search.py

**Problem:** You run the same kind of web search often and want it repeatable,
filterable, and saved, not a throwaway browser tab you re-type every time.

**Solution:** A config-driven Tavily search. Set the query and optional filters
at the top (allowed/forbidden sites, a time window, result count, general vs
news), run it, and get ranked results plus an optional short AI summary. With
`TIMESTAMP_FILENAME` on, each run saves to a dated file, so repeating a query
builds a history.

**Why this approach:** Tavily is itself an LLM-powered search service, so the
search and the optional summary come straight from its API, with no reason to
add another LLM of our own. A single API call is the right, simplest tool here.

**Why not just ask ChatGPT to browse?** A chatbot gives a throwaway answer. This
pins your allowed/forbidden sites and time window exactly, returns structured,
linkable results, and (with a timestamped file) saves each run, so repeating the
same search builds an archive instead of a one-off.

Run:

    pip install tavily-python python-dotenv
    # .env next to the script:  TAVILY_API_KEY=tvly-...
    python web_search.py

### web_search_agent.py

**Problem:** Some questions you can answer from what you already know; others
need a quick web look first, and sometimes more than one. You want one thing you
can point at a question and trust to work out which case it is.

**Solution:** A tiny ReAct agent, hand-built as a LangGraph graph (a model node
and a tool node joined by conditional routing) so the control flow is visible.
It has a single tool: web search (Brave, a different backend from `web_search.py`
above, which uses Tavily). Put a question at the top; the agent decides whether
to search, refines and searches again if the results are thin (up to
`MAX_SEARCHES`), then answers with sources. If it already knows, it answers with
zero searches.

**Why this approach:** This is the one script in the repo that genuinely needs
an agent. The number of steps is not known in advance (it depends on the
question and on what each search returns), so the flow cannot be a fixed single
call or a straight line. One tool is enough; the agency is in the decision
(whether to search, how many times, when to stop), not in having many tools.

**Why not just ChatGPT?** A browser chatbot can answer interactively. The script
makes it reproducible and scriptable: a fixed question, a bounded number of
searches, and the answer saved with its exact sources to disk. It is also a
clear, minimal example of how the decide-and-search loop actually works.

Run:

    pip install langgraph langchain-openai httpx python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...  and  BRAVE_API_KEY=...
    python web_search_agent.py
