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
| [audio_transcriber.py](#audio_transcriberpy) | transcribes audio/video to text (local Whisper or cloud) | speech-to-text |
| [doc_finder.py](#doc_finderpy) | semantic search over a folder of documents | single LLM call |
| [folder_tidy.py](#folder_tidypy) | sorts a folder into category subfolders (LLM), safely | single LLM call |
| [form_from_text.py](#form_from_textpy) | fills a form (your fields) from a long text, as JSON | single LLM call |
| [form_interview.py](#form_interviewpy) | fills a form by chatting until it's complete, as JSON | conversational |
| [local_llm.py](#local_llmpy) | run an instruction over a text with a local model (Ollama) | single LLM call (local) |
| [mail_finder.py](#mail_finderpy) | semantic search over an exported mailbox | single LLM call |
| [meeting_notes.py](#meeting_notespy) | turns a transcript into structured minutes | single LLM call |
| [rename_files.py](#rename_filespy) | bulk-rename files in a folder, safely | rules, no LLM (optional LLM assist) |
| [summarize_folder.py](#summarize_folderpy) | summarizes every document in a folder into one index | map-reduce (Gemini) |
| [supervisor_assistant.py](#supervisor_assistantpy) | routes a request to expert agents (web + your docs) and synthesizes | multi-agent supervisor (LangGraph) |
| [web_search.py](#web_searchpy) | repeatable web search via Tavily, saved to disk | search API (Tavily) |
| [web_search_agent.py](#web_search_agentpy) | answers a question, deciding whether and how often to web-search | ReAct agent (LangGraph) |

<!--
Per-script sections go below, alphabetical by filename (matching GitHub's
file list). Each section's heading is just the script name so the table
link anchors stay clean, e.g. [foo.py](#foopy) jumps to `### foo.py`.
-->

### audio_transcriber.py

**Problem:** You have recordings (interviews, lectures, voice memos) and need
them as text, ideally without uploading private audio anywhere.

**Solution:** Point it at an audio/video file or a folder; it writes a `.txt`
transcript for each (next to it, or in `OUTPUT_DIR`). One `ENGINE` flag chooses
`faster-whisper` (runs Whisper locally, free, audio never leaves your machine,
downloads the model once) or `openai` (cloud Whisper API, no setup, pay per
minute). Pick a model size to trade speed for accuracy.

**Why this approach:** Transcription is a solved, dedicated task (Whisper), not
something to hand to a chat model. Local-first is the honest default: this is the
one script in the repo where nothing has to leave your machine, which matters for
confidential recordings.

**Why not just ChatGPT?** You would upload each file by hand and could not batch
a folder; in local mode this sends nothing at all. It also writes a clean `.txt`
per recording that the other scripts (`summarize_folder`, `meeting_notes`) can
read.

Run:

    # local (default): pip install faster-whisper
    # cloud: pip install openai python-dotenv  (+ OPENAI_API_KEY in .env)
    python audio_transcriber.py

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

**Also useful for:** by changing `QUERY`, this doubles as a PII or
sensitive/harmful-content scan across a folder of documents. Same caveat as
`mail_finder`: it is triage for human review, not a guaranteed detector.

Run:

    pip install anthropic python-dotenv     # + pypdf / python-docx for those formats
    # .env next to the script:  ANTHROPIC_API_KEY=sk-ant-...
    python doc_finder.py

### folder_tidy.py

**Problem:** A folder where files belong in meaningful buckets (invoices,
contracts, reports) that a by-type sort cannot tell apart, and you do not want to
file each one by hand.

**Solution:** List the `CATEGORIES` you want at the top; it reads each file (its
name, or `.txt`/`.md` content if `READ_CONTENT` is on), picks the best-fit
category, shows a dry-run table (file to category), and only moves files into
those subfolders when `APPLY` is True. It never overwrites (colliding names get a
`_1` suffix) and skips files that are already sorted.

**Why this approach:** This is where an LLM earns its place, unlike
`rename_files`: sorting by *meaning* into your own categories is a judgement a
rules engine cannot make. It is still one classification call per file, no agent,
and the move stays behind a dry-run and an `APPLY` switch.

**Why not just ChatGPT?** A chatbot cannot move files on your disk. This does the
sorting for real, across a whole folder, safely (preview first), into the exact
categories you defined.

Run:

    pip install openai python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...
    python folder_tidy.py

### form_from_text.py

**Problem:** You have a long text (an email, a report, notes, a CV) and need the
same handful of fields pulled out of it every time, as clean structured data
rather than by hand.

**Solution:** Define the form once at the top (`FORM_FIELDS`, each with a name
and a plain-language description), point it at a text file (or paste the text
inline), and it extracts those fields in a single structured LLM call and writes
them out as JSON. It fills only what the text actually contains and leaves
anything it cannot find as `null`, and it reports which required fields were
missing, so it never invents a value.

**Why this approach:** The data already exists in the text, so this is a
one-shot extraction: a single LLM call with a structured-output schema (a
Pydantic model built from your fields). No chat and no agent, because there is
nothing to decide or ask, only to extract.

**Why not just ChatGPT?** Pasting one document into a chat works once. This
applies the exact same field set to any text, every time, returns machine
readable JSON you can feed into something else, and (with the null-if-absent
rule) is honest about what the text did not contain instead of quietly filling
gaps.

Run:

    pip install openai python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...
    python form_from_text.py

### form_interview.py

**Problem:** Sometimes the form data does not exist in a document yet, it is in
someone's head. You want to collect a fixed set of fields from a person without
building a UI.

**Solution:** The conversational companion to `form_from_text.py`, using the
same `FORM_FIELDS`. It chats with you one question at a time, filling fields as
you answer, and stops once every required field is present, then saves JSON.
Each turn is one structured-output call returning the fields so far, the next
question, and whether the form is complete. It records only what you actually
say.

**Why this approach:** This is the one script in the repo that genuinely needs a
chat loop. You cannot fill a form up front when the answers do not exist yet, so
the number of turns is not fixed; it depends on how much the person gives per
message. That back-and-forth is the tool the task calls for.

**Why not just ChatGPT?** A chatbot could ask similar questions, but this pins
the exact field set, guarantees structured JSON at the end (not prose), enforces
the required fields before finishing, and will not drift off task. It is a form,
not a conversation that happens to mention the fields.

Run:

    pip install openai python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...
    python form_interview.py

### local_llm.py

**Problem:** You want to summarize, rewrite, or pull points out of a text, but
the text is confidential, so sending it to a cloud API is not an option.

**Solution:** Write an `INSTRUCTION` (summarize, rewrite formally, extract key
points, answer a question) and point it at a text; it runs that on a local model
through Ollama and prints or saves the result. One call, no cloud, no API key,
nothing leaves your machine.

**Why this approach (and why local):** The task is a single instruction over a
text, so it is one LLM call, no agent. Running it on Ollama is the point: for
sensitive material, free and fully offline beats cloud quality. It is the LLM
counterpart to `audio_transcriber`'s local Whisper.

**Why not just ChatGPT?** ChatGPT would mean uploading the text. This keeps
confidential content on your machine, costs nothing, and works with no internet.
(A local model is a bit less capable than a frontier cloud one, which is the
honest trade for privacy.)

Run:

    # install Ollama from https://ollama.com, then:  ollama pull llama3.1
    pip install ollama
    python local_llm.py

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

**Also useful for:** the match is only your `QUERY`, so the same script becomes a
first-pass scanner for emails containing personal data (PII), credentials, or
sensitive/harmful content, whatever you can describe. Treat it as triage that
surfaces candidates for review, not a compliance-grade detector (an LLM can miss
cases).

Run:

    pip install openai python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...
    python mail_finder.py

### meeting_notes.py

**Problem:** After a meeting you have a transcript but need the useful part: what
was decided, who owns what, and what is still open, without re-reading the whole
thing.

**Solution:** Point it at a transcript (a text file, or paste it) and it extracts
structured minutes in one call: a short summary, the decisions, action items with
owners, and open questions, as clean markdown. It pairs with `audio_transcriber.py`
(feed it that `.txt`) but works on any transcript.

**Why this approach:** The information is all in the transcript, so it is a
one-shot structured extraction (same tier as `form_from_text`, richer shape). No
agent needed. It is told to use only what was said, so it will not invent a
decision or assign an owner nobody named.

**Why not just ChatGPT?** You would paste the transcript and get prose. This
gives the same fixed structure every time (summary / decisions / actions /
questions), saves it to a file, and chains cleanly after the transcriber:
consistent output you can file or feed onward, not a one-off answer.

Run:

    pip install openai python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...
    python meeting_notes.py

### rename_files.py

**Problem:** A folder full of messily named files (`My File FINAL (1).pdf`,
`IMG_2394.jpg`) that you want cleaned up or consistently named, without renaming
each one by hand.

**Solution:** Point it at a folder and pick a mode. **Rules mode** (default, no
LLM, no dependencies) tidies each name: lowercase, swap spaces, strip junk words,
with an optional date or sequential-number prefix. **LLM mode** (`USE_LLM=True`)
lets a model propose a fresh descriptive name from the filename (and optionally
`.txt`/`.md` content). Either way it prints a dry-run table and renames only when
`APPLY=True`; it never overwrites (colliding names get `_1`, `_2`) and renames in
two phases so files can swap names safely.

**Why this approach:** This is the repo's no-AI example, on purpose. A
rules-based rename needs no model at all, so the default mode has zero
dependencies and zero cost. The LLM is opt-in, for the one case where the
filenames carry nothing to work from. Using AI here by default would be the
wrong tool.

**Why not just ChatGPT?** A chatbot cannot rename files on your disk. This does
the actual renaming, safely (dry-run first, no overwrites), across a whole folder
at once, and for the common case without sending anything anywhere.

Run:

    # rules mode: nothing to install
    python rename_files.py
    # LLM mode: pip install openai python-dotenv  (+ OPENAI_API_KEY in .env)

### summarize_folder.py

**Problem:** A folder of documents you need the gist of without reading each one:
which files cover what, and what the whole set is about.

**Solution:** Point it at a folder; it summarizes each document in a few
sentences, then writes a single markdown index, an overview of the whole
collection followed by a per-file summary. Reads `.txt`/`.md` out of the box,
with `.pdf`/`.docx` via optional `pypdf`/`python-docx`.

**Why this approach (and why Gemini):** Summarizing a folder is a map-reduce job,
summarize each file, then summarize the summaries. It runs on Google Gemini
specifically because its very large context window suits long documents: you can
feed a lot of each file in one call. That is a real reason to pick Gemini here,
not a token appearance, and it is why this is the repo's Gemini script.

**Why not just ChatGPT?** A chatbot summarizes one pasted document at a time.
This walks a whole folder, reads your local files (including formats you would
otherwise convert by hand), and leaves you a saved index you can keep and
re-generate.

Run:

    pip install google-genai python-dotenv     # + pypdf / python-docx for those formats
    # .env next to the script:  GEMINI_API_KEY=...
    python summarize_folder.py

### supervisor_assistant.py

**Problem:** Some requests span more than one domain at once, "how does my saved
note on X compare to the latest online?" needs both your local files and the web,
and a single tool or agent handles that awkwardly.

**Solution:** A hand-built multi-agent supervisor. One request goes in; a
supervisor decides which expert agent should act next, lets it work, and repeats
until it can answer, then synthesizes. Two workers, each a genuine multi-step
agent: `web_research` (Brave search, refines its queries) and `docs` (searches
your local folder, decides which files to open and read). Built as a plain
LangGraph `StateGraph`, a supervisor node, one node per worker, a finalize node,
conditional routing, and a step cap, with no `create_supervisor` and no
`create_react_agent`, so the control flow is fully visible.

**Why this approach (honestly):** A supervisor earns its place only when subtasks
span distinct domains and each genuinely needs its own loop, exactly the case here
(the web vs. your files), and the payoff is that it can chain them for one
request. For a single-domain task, a single ReAct agent (`web_search_agent`) is
the right tool, not this. The workers are deliberately read-only (search/read),
no autonomous file changes.

**Why not just ChatGPT?** It searches your own local documents and the live web in
one pass, using tools a chat window does not have, and keeps the file-reading on
your machine. The result is a synthesis grounded in both, with sources.

Run:

    pip install langgraph langchain-openai httpx python-dotenv
    # .env next to the script:  OPENAI_API_KEY=sk-...  and  BRAVE_API_KEY=...
    python supervisor_assistant.py

### web_search.py

**Problem:** You run the same kind of web search often and want it repeatable,
filterable, and saved, not a throwaway browser tab you re-type every time.

**Solution:** A config-driven Tavily search. Set the query and optional filters
at the top (allowed/forbidden sites, a time window, result count, general vs
news), run it, and get ranked results plus an optional short AI summary. With
`TIMESTAMP_FILENAME` on, each run saves to a dated file, so repeating a query
builds a history. Set `REPEAT` on with a `CYCLE_MINUTES` interval to keep
re-running it automatically as a simple monitor (Ctrl+C to stop).

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

## Running on a schedule

Every script here is one-shot (it does its job and exits), so you can schedule any
of them the normal way, no code needed:

- **Windows (Task Scheduler):** create a Basic Task, set a trigger (e.g. daily at
  08:00), and point the action at `python C:\path\to\script.py`. It runs even when
  no terminal is open, and survives a reboot.
- **macOS / Linux (cron):** add a line like
  `0 8 * * * /usr/bin/python3 /path/to/script.py`.

For a quick "keep re-running while I'm working" loop without the OS scheduler,
`web_search.py` has a built-in `REPEAT` / `CYCLE_MINUTES` option (Ctrl+C to stop).
