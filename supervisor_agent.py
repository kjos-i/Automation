"""supervisor_agent.py - a hand-built multi-agent supervisor (the capstone).

One REQUEST in. A supervisor decides which expert *agent* should act next, lets it
work, and repeats until it has enough to answer, then synthesizes the result.
Two workers, each a genuine multi-step agent in a different domain:

  - web_research : searches the web (Brave), refining as needed.
  - docs         : searches the user's local folder, decides which files to open
                   and read, then answers from them.

The whole thing is a hand-built LangGraph StateGraph (a supervisor node, one node
per worker, a finalize node, conditional routing, a step cap) - no
create_supervisor, no create_react_agent. That is the point: the control flow is
visible.

Honest note: a supervisor only earns its place when subtasks span distinct
domains and each genuinely needs its own loop (as here: the web vs. your files).
For a single-domain task, one ReAct agent (see web_search_agent.py) is the right
tool, not this.

Setup:
    pip install langgraph langchain-openai httpx python-dotenv
    # .env next to this script:
    #   OPENAI_API_KEY=sk-...
    #   BRAVE_SEARCH_API_KEY=...
    python supervisor_agent.py
"""

GUI = True  # show this script in the Automation GUI window

# ================= CONFIG - edit these, then run =================
REQUEST = "How does my saved note on battery recycling compare to the latest online?"

DOCS_FOLDER = r"C:\path\to\documents"  # the folder the docs agent searches

MODEL = "gpt-4o-mini"
MAX_STEPS = 4  # cap on worker delegations before the supervisor must answer
RESULTS_PER_SEARCH = 5
DOC_CHAR_LIMIT = 4000

SAVE_ANSWER_TO_FILE = False
OUTPUT_FILE = r"C:\path\to\answer.md"  # used only if SAVE_ANSWER_TO_FILE
# ================================================================

import os
import re
import sys
from pathlib import Path
from typing import Annotated, Literal, TypedDict

import httpx
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel

load_dotenv()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


# --- web_research worker's tool: Brave search ---
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


@tool
def web_search(query: str) -> str:
    """Search the web (Brave) for current or external information."""
    headers = {"X-Subscription-Token": os.getenv("BRAVE_SEARCH_API_KEY", ""), "Accept": "application/json"}
    try:
        r = httpx.get(
            BRAVE_ENDPOINT, headers=headers, params={"q": query, "count": RESULTS_PER_SEARCH}, timeout=30
        )
        r.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Search error: {exc}"
    out = []
    for item in r.json().get("web", {}).get("results", []):
        out.append(f"- {_clean(item.get('title', ''))} ({item.get('url')})\n  {_clean(item.get('description', ''))[:200]}")
    return "\n".join(out) or "No results."


# --- docs worker's tools: search + read local files ---
def _docs() -> list:
    base = Path(DOCS_FOLDER)
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in (".txt", ".md")]


@tool
def search_docs(query: str) -> str:
    """Search the local document folder; returns the most relevant filenames with a snippet."""
    words = set(re.findall(r"\w+", query.lower()))
    scored = []
    for p in _docs():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = text.lower()
        score = sum(low.count(w) for w in words)
        if score:
            scored.append((score, p.name, text[:200].replace("\n", " ")))
    scored.sort(reverse=True)
    if not scored:
        return "No matching documents."
    return "\n".join(f"- {name}: {snippet}" for _score, name, snippet in scored[:5])


@tool
def read_doc(filename: str) -> str:
    """Read the full text of a document in the folder by its filename."""
    for p in _docs():
        if p.name.lower() == filename.lower():
            try:
                return p.read_text(encoding="utf-8", errors="replace")[:DOC_CHAR_LIMIT]
            except OSError as exc:
                return f"Could not read {filename}: {exc}"
    return f"No document named {filename}."


# --- A hand-built ReAct agent factory (used for each worker) ---
def build_react_agent(tools: list, system_prompt: str):
    model = ChatOpenAI(model=MODEL, temperature=0).bind_tools(tools)

    def agent_node(state: MessagesState):
        return {"messages": [model.invoke([SystemMessage(content=system_prompt), *state["messages"]])]}

    def should_continue(state: MessagesState):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


web_agent = build_react_agent(
    [web_search],
    "You are a web research agent. Use web_search to find current, external "
    "information; refine the query if the first results are thin, then answer "
    "concisely with source URLs.",
)
docs_agent = build_react_agent(
    [search_docs, read_doc],
    "You are a document agent for the user's local files. Use search_docs to find "
    "relevant files, then read_doc to read the ones that look useful, then answer "
    "from them and cite the filenames. If nothing relevant is found, say so.",
)


# --- The hand-built supervisor graph ---
class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    next: str


class Route(BaseModel):
    next: Literal["web_research", "docs", "FINISH"]


SUPERVISOR_PROMPT = (
    "You coordinate two expert agents:\n"
    "- web_research: searches the web for current or external information.\n"
    "- docs: searches the user's local document folder.\n"
    "Look at the conversation and decide who should act NEXT to make progress on "
    "the request, or FINISH once enough has been gathered to answer. Do not call an "
    "agent again unless more from it is genuinely needed."
)

_router = ChatOpenAI(model=MODEL, temperature=0).with_structured_output(Route)


def supervisor_node(state: SupervisorState):
    worker_runs = sum(1 for m in state["messages"] if isinstance(m, AIMessage) and m.content.startswith("["))
    if worker_runs >= MAX_STEPS:
        return {"next": "FINISH"}
    decision = _router.invoke([SystemMessage(content=SUPERVISOR_PROMPT), *state["messages"]])
    return {"next": decision.next}


def _run_worker(agent, label: str):
    result = agent.invoke({"messages": [HumanMessage(content=REQUEST)]})
    answer = result["messages"][-1].content
    return {"messages": [AIMessage(content=f"[{label}] {answer}")]}


def web_node(state: SupervisorState):
    return _run_worker(web_agent, "web_research")


def docs_node(state: SupervisorState):
    return _run_worker(docs_agent, "docs")


def finalize_node(state: SupervisorState):
    llm = ChatOpenAI(model=MODEL, temperature=0)
    # Collect the workers' findings (the [label]-tagged messages) as DATA to synthesize,
    # rather than replaying them as prior assistant turns (which the model tends to just echo).
    findings = "\n\n".join(
        m.content for m in state["messages"] if isinstance(m, AIMessage) and m.content.startswith("[")
    )
    prompt = (
        f"User request:\n{REQUEST}\n\n"
        f"Findings gathered by the expert agents:\n{findings}\n\n"
        "Write one clear answer to the request using ALL relevant findings. If the local "
        "documents turned up nothing, still give the online information that was found "
        "(do not just say you couldn't find a local note). Cite sources or filenames where given."
    )
    msg = llm.invoke(
        [
            SystemMessage(content="You synthesize the agents' findings into one clear, complete answer."),
            HumanMessage(content=prompt),
        ]
    )
    return {"messages": [msg]}


_graph = StateGraph(SupervisorState)
_graph.add_node("supervisor", supervisor_node)
_graph.add_node("web_research", web_node)
_graph.add_node("docs", docs_node)
_graph.add_node("finalize", finalize_node)
_graph.add_edge(START, "supervisor")
_graph.add_conditional_edges(
    "supervisor",
    lambda s: s["next"],
    {"web_research": "web_research", "docs": "docs", "FINISH": "finalize"},
)
_graph.add_edge("web_research", "supervisor")
_graph.add_edge("docs", "supervisor")
_graph.add_edge("finalize", END)
supervisor = _graph.compile()


def main() -> None:
    missing = [k for k in ("OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY") if not os.getenv(k)]
    if missing:
        sys.exit(
            "Missing key(s) in .env next to this script: "
            + ", ".join(missing)
            + "\n  OPENAI_API_KEY=sk-...\n  BRAVE_SEARCH_API_KEY=..."
        )

    print(f"Request: {REQUEST}\n")
    result = supervisor.invoke({"messages": [HumanMessage(content=REQUEST)], "next": ""})

    for m in result["messages"]:
        if isinstance(m, AIMessage) and m.content.startswith("["):
            print(f"  [{m.content.split(']')[0][1:]} agent ran]")

    answer = result["messages"][-1].content
    print(f"\nAnswer:\n{answer}")

    if SAVE_ANSWER_TO_FILE:
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(OUTPUT_FILE).write_text(f"# {REQUEST}\n\n{answer}\n", encoding="utf-8")
        print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
