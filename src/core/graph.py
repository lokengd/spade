from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import Send
import logging

from src.core.state import SpadeState, P_UNCONSTRAINED
from config.settings import K_PATTERNS, N_OUTER_LOOPS, M_INNER_LOOPS
from src.utils.logger import log
from src.agents import (
    fl_ensemble, reproduction, pattern_selection, patchgen, debaters, judge, test_agent
)

logger = logging.getLogger(__name__)

def activate_patchgen_agents(state: SpadeState):
    """Dynamically activates K+1 parallel patch generation agents."""
    sends = []
    
    # Grab the current counters to pass them down
    current_n = state.get("outer_loop_count", 1)
    current_m = state.get("inner_loop_count", 1)
    current_v = state.get("current_patch_version", 1)

    # Activate K agents
    for pattern in state.get("selected_patterns", [])[:K_PATTERNS]:
        sends.append(Send("generate_v1_patch", {
            "active_pattern": pattern,
            "bug_context": state["bug_context"],
            "outer_loop_count": current_n,
            "inner_loop_count": current_m,
            "current_patch_version": current_v
        }))
        
    # Activate the +1 Unconstrained LLM agent
    sends.append(Send("generate_v1_patch", {
        "active_pattern": P_UNCONSTRAINED,
        "bug_context": state["bug_context"],
        "outer_loop_count": current_n,
        "inner_loop_count": current_m,
        "current_patch_version": current_v
    }))
    
    return sends

def route_after_v1(state: SpadeState):
    return "end" if state["resolution_status"] == "resolved" else "debate_panel"

def route_after_refined(state: SpadeState):
    # Success! Exit the graph.
    if state["resolution_status"] == "resolved":
        return "end"
        
    # Hard Stop check - if test_agent signaled failure or counters exceed limit
    if state["resolution_status"] == "failed" or state.get("outer_loop_count", 1) > N_OUTER_LOOPS:        
        log(f"MAX LIMITS REACHED. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
        
    # Case 1: Transition to new Outer Loop (N+1)
    if state["resolution_status"].startswith("N") and state["resolution_status"].endswith("_failed"):
        log("Transitioning to new Outer Loop (Pattern Selection).", "Orchestrator")
        return "pattern_selection"

    # Case 2: Backtracking (pick new winner) or Iterative Refinement (v+1)
    # Both stay in the debate panel.
    return "debate_panel"


def build_graph():

    graph = StateGraph(SpadeState)

    # Add nodes
    graph.add_node("fl_ensemble", fl_ensemble.run)
    graph.add_node("reproduction", reproduction.run)
    graph.add_node("pattern_selection", pattern_selection.run)
    graph.add_node("generate_v1_patch", patchgen.generate_v1_patch)    
    graph.add_node("initial_verification", test_agent.verify_v1)
    # Debate panel nodes
    graph.add_node("debate_panel", lambda state: {}) # Dummy node to trigger parallel fan-out
    graph.add_node("generate_dynamic_arg", debaters.generate_dynamic_arg)
    graph.add_node("generate_static_arg", debaters.generate_static_arg)
    graph.add_node("exchange_arguments", debaters.exchange_arguments)    
    graph.add_node("generate_dynamic_rebuttal", debaters.generate_dynamic_rebuttal)
    graph.add_node("generate_static_rebuttal", debaters.generate_static_rebuttal)
    graph.add_node("judge_verdict", judge.run)
    graph.add_node("generate_refined_patch", patchgen.generate_refined_patch) 
    graph.add_node("verify_refined", test_agent.verify_refined)        

    # Add edges
    graph.add_edge(START, "fl_ensemble")
    graph.add_edge("fl_ensemble", "reproduction")
    graph.add_edge("reproduction", "pattern_selection")
    # Fan-Out to K+1 PatchGen agents using the dynamic Send API
    graph.add_conditional_edges(
        "pattern_selection", 
        activate_patchgen_agents, 
        ["generate_v1_patch"] # The node we are sending to
    )
    # Fan-In: Wait for all K+1 patches, then go to verification
    graph.add_edge("generate_v1_patch", "initial_verification")
    # Conditional route to Debate Setup
    graph.add_conditional_edges("initial_verification", route_after_v1, {
        "end": END, 
        "debate_panel": "debate_panel"
    })
    
    # Debate panel edges
    # Fan-Out 1: Both debaters generate arguments simultaneously
    graph.add_edge("debate_panel", "generate_dynamic_arg")
    graph.add_edge("debate_panel", "generate_static_arg")

    # Fan-In 1: Wait for BOTH arguments to finish before exchanging
    graph.add_edge("generate_dynamic_arg", "exchange_arguments")
    graph.add_edge("generate_static_arg", "exchange_arguments")
    
    # Fan-Out 2: Both debaters read the exchanged state and write rebuttals
    graph.add_edge("exchange_arguments", "generate_dynamic_rebuttal")
    graph.add_edge("exchange_arguments", "generate_static_rebuttal")
    
    # Fan-In 2: Wait for BOTH rebuttals before passing to the Judge
    graph.add_edge("generate_dynamic_rebuttal", "judge_verdict")
    graph.add_edge("generate_static_rebuttal", "judge_verdict")
    
    # Judge to select winner to generate next version for re-verification
    graph.add_edge("judge_verdict", "generate_refined_patch")
    graph.add_edge("generate_refined_patch", "verify_refined")
    
    graph.add_conditional_edges("verify_refined", route_after_refined, {
        "end": END, 
        "pattern_selection": "pattern_selection", 
        "debate_panel": "debate_panel",
        "hard_stop": END
    })

    return graph


# Generate Architecture Diagram
def draw_graph(app):
    file_name = "spade_graph.png"
    print("\nGenerating graph...")
    try:
        png_data = app.get_graph().draw_mermaid_png()
        with open(file_name, "wb") as f:
            f.write(png_data)
        print(f"Saved graph image to {file_name}")
    except Exception as e:
        print(f"Could not generate PNG: {e}")
