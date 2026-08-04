"""web_search_agent.py - a tiny ReAct agent that answers a question, searching if needed.

Built on a hand-made LangGraph graph (explicit model node + tool node joined by
conditional routing), not the prebuilt helper, so the control flow is visible.
It has ONE tool: web search. The point of an agent here is the *decision* - for
a given question it decides whether to search at all, how many times to refine,
and when it has enough to answer. Trivial questions get answered with zero
searches; open ones trigger one or more.

One-shot: set QUESTION at the top, run it, get an answer with sources. No chat
loop.

Setup:
    pip install langgraph langchain-openai httpx python-dotenv
    # put your keys in a .env file next to this script:
    #   OPENAI_API_KEY=sk-...
    #   BRAVE_API_KEY=...
    python web_search_agent.py
"""

# ================= CONFIG - edit these, then run =================
QUESTION = "What are the latest EU rules on battery recycling, and when do they take effect?"

MODEL = "gpt-4o-mini"
MAX_SEARCHES = 3  # hard cap on how many times the agent may search before it must answer
RESULTS_PER_SEARCH = 5

SAVE_ANSWER_TO_FILE = False
OUTPUT_FILE = r"C:\path\to\answer.md"  # used only if SAVE_ANSWER_TO_FILE
# ================================================================

import os
import re
import sys
from pathlib import Path
from typing import Annotated, Sequence, TypedDict

import httpx
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

load_dotenv()


# --- The one tool: web search (Brave) ---
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _clean(text: str) -> str:
    """Strip Brave's <strong> highlight tags and tidy whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


@tool
def web_search(query: str) -> str:
    """Search the web and return the top results. Use this only when the
    question needs current, factual, or external information you are unsure of.

    Args:
        query (str): What to search for.
    """
    headers = {
        "X-Subscription-Token": os.getenv("BRAVE_API_KEY", ""),
        "Accept": "application/json",
    }
    params = {"q": query, "count": RESULTS_PER_SEARCH}
    try:
        resp = httpx.get(BRAVE_ENDPOINT, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Search error: {exc}"  # let the agent recover instead of crashing
    results = resp.json().get("web", {}).get("results", [])
    lines = []
    for r in results:
        snippet = _clean(r.get("description", ""))[:300]
        lines.append(f"- {_clean(r.get('title', ''))} ({r.get('url')})\n  {snippet}")
    return "\n".join(lines) or "No results."


tools = [web_search]

# --- LLM: one bound to the tool, one without (to force a final answer at the cap) ---
_base_model = ChatOpenAI(model=MODEL, temperature=0)
_model_with_tools = _base_model.bind_tools(tools)

SYSTEM_PROMPT = SystemMessage(
    content=(
        "You are a helpful assistant. Answer the user's question clearly. If it "
        "needs current, factual, or external information you are unsure of, use the "
        f"web_search tool (you may search up to {MAX_SEARCHES} times, refining the "
        "query if the first results are thin). If you already know the answer, just "
        "answer without searching. When you rely on search results, give a concise "
        "answer and list the source URLs you used."
    )
)


# --- Agent state ---
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# --- Graph nodes ---
def agent_node(state: AgentState) -> AgentState:
    """Call the model. Once the search cap is reached, drop the tools so the
    model has no choice but to write its final answer."""
    searches = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
    llm = _model_with_tools if searches < MAX_SEARCHES else _base_model
    response = llm.invoke([SYSTEM_PROMPT] + list(state["messages"]))
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """Route to the tool node when the model asked to search, otherwise finish."""
    last_message = state["messages"][-1]
    # getattr guard: a plain answer message has no tool_calls.
    if getattr(last_message, "tool_calls", None):
        return "continue"
    return "end"


# --- Graph assembly (same shape as the minimal version: model <-> tool) ---
graph = StateGraph(AgentState)
graph.add_node("agent_node", agent_node)
graph.add_node("tool_node", ToolNode(tools))

graph.add_edge(START, "agent_node")
graph.add_conditional_edges(
    "agent_node",
    should_continue,
    {"continue": "tool_node", "end": END},
)
graph.add_edge("tool_node", "agent_node")

agent = graph.compile()


# --- One-shot run ---
def _searches_run(messages) -> list:
    """The queries the agent chose to run (empty if it answered directly)."""
    return [
        call["args"].get("query", "")
        for m in messages
        if getattr(m, "tool_calls", None)
        for call in m.tool_calls
        if call["name"] == "web_search"
    ]


def save_answer(question: str, answer: str, searches: list, path: str) -> None:
    lines = [f"# {question}", ""]
    if searches:
        lines += ["**Searches run:**", *[f"- {q}" for q in searches], ""]
    lines += ["## Answer", "", answer]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    missing = [k for k in ("OPENAI_API_KEY", "BRAVE_API_KEY") if not os.getenv(k)]
    if missing:
        sys.exit(
            "Missing key(s) in .env next to this script: "
            + ", ".join(missing)
            + "\n  OPENAI_API_KEY=sk-...\n  BRAVE_API_KEY=..."
        )

    print(f"Question: {QUESTION}\n")
    result = agent.invoke({"messages": [HumanMessage(content=QUESTION)]})
    messages = result["messages"]

    searches = _searches_run(messages)
    if searches:
        print(f"The agent decided to search {len(searches)} time(s):")
        for q in searches:
            print(f"  - {q}")
    else:
        print("The agent answered directly (no search needed).")

    answer = messages[-1].content
    print(f"\nAnswer:\n{answer}")

    if SAVE_ANSWER_TO_FILE:
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
        save_answer(QUESTION, answer, searches, OUTPUT_FILE)
        print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
