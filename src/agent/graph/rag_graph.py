from langgraph.graph import StateGraph, END

from app import retrieve_node, build_prompt_node
from src.agent.state.rag_state import RAGState


def build_graph():
    workflow = StateGraph(RAGState)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("build_prompt", build_prompt_node)
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "build_prompt")
    workflow.add_edge("build_prompt", END)
    return workflow.compile()
