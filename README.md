# Automation

Small, single-purpose scripts that take a prompt, decide what to do, and do it,
so I don't have to. Each script uses the simplest approach that fits the task:
a single LLM call, a graph, or a full agent. The right tool for the job, not one
pattern forced onto every problem.

**Author:** Ingrid Kjos ([ORCID 0000-0002-9166-3074](https://orcid.org/0000-0002-9166-3074))

## Scripts

| Script | Does | Approach |
|--------|------|----------|
| [mail_finder.py](#mail_finderpy) | semantic search over an exported mailbox | single LLM call |

<!--
Per-script sections go below, alphabetical by filename (matching GitHub's
file list). Each section's heading is just the script name so the table
link anchors stay clean, e.g. [foo.py](#foopy) jumps to `### foo.py`.
-->

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

Run:

    pip install openai python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...
    python mail_finder.py
