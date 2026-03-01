from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import Send

from src.core.state import SpadeState
from config.settings import K_PATTERNS, N_OUTER_LOOPS, M_INNER_LOOPS
from src.agents import (
    fl_ensemble, reproduction, pattern_selection, patchgen, 
    debaters, judge, test_agent
)

def activate_patchgen_agents(state: SpadeState):
    """Dynamically activates K+1 parallel patch generation agents."""
    sends = []
    # Activate K agents (slice the list just in case the LLM returns more than K)
    for pattern in state.get("selected_patterns", [])[:K_PATTERNS]:
        sends.append(Send("generate_v1_patch", {
            "active_pattern": f"pattern: {pattern}",
            "bug_context": state["bug_context"]
        }))
        
    # Activate the +1 Unconstrained agent
    sends.append(Send("generate_v1_patch", {
        "active_pattern": "unconstrained",
        "bug_context": state["bug_context"]
    }))
    return sends


def route_after_v1(state: SpadeState):
    return "end" if state["resolution_status"] == "resolved" else "debate_panel"

def route_after_refined(state: SpadeState):
    # 1. Success! Exit the graph.
    if state["resolution_status"] == "resolved":
        return "end"
        
    # 2. Check if we hit a RESET or BACKTRACK condition
    if state.get("current_patch_version") == 1:
        
        # A: Hard Reset (hit M limit) -> Go back to Pattern Selection
        if state.get("inner_loop_count") == 0:
            if state.get("outer_loop_count") >= N_OUTER_LOOPS:
                return "hard_stop"
            return "pattern_selection"
            
        # B: Backtrack (hit V limit) -> Go back to the start of the Debate Panel
        return "debate_panel"

    # 3. Deepen -> Go back to the Debate Panel to generate v3, v4, etc.
    return "debate_panel"


def build_spade_orchestrator():

    workflow = StateGraph(SpadeState)

    # 1. Add Core Nodes
    workflow.add_node("fl_ensemble", fl_ensemble.run)
    workflow.add_node("reproduction", reproduction.run)
    workflow.add_node("pattern_selection", pattern_selection.run)
    workflow.add_node("generate_v1_patch", patchgen.generate_v1_patch)    
    workflow.add_node("initial_verification", test_agent.verify_v1)
    
    # 2. Add Inner Loop Nodes (Debate Panel Parallel Architecture)
    workflow.add_node("debate_panel", lambda state: {}) # Dummy node to trigger parallel fan-out
    workflow.add_node("generate_dynamic_arg", debaters.generate_dynamic_arg)
    workflow.add_node("generate_static_arg", debaters.generate_static_arg)
    
    workflow.add_node("exchange_arguments", debaters.exchange_arguments)
    
    workflow.add_node("generate_dynamic_rebuttal", debaters.generate_dynamic_rebuttal)
    workflow.add_node("generate_static_rebuttal", debaters.generate_static_rebuttal)
    
    workflow.add_node("judge_verdict", judge.run)
    workflow.add_node("generate_refined_patch", patchgen.generate_refined_patch) 
    workflow.add_node("verify_refined", test_agent.verify_refined)        

    # 3. Outer Pipeline Edges
    workflow.add_edge(START, "fl_ensemble")
    workflow.add_edge("fl_ensemble", "reproduction")
    workflow.add_edge("reproduction", "pattern_selection")

    # 4. Fan-Out to K+1 PatchGen Agents using the dynamic Send API
    workflow.add_conditional_edges(
        "pattern_selection", 
        activate_patchgen_agents, 
        ["generate_v1_patch"] # The node we are sending to
    )

    # 5. Fan-In: Wait for all K+1 patches, then go to verification
    workflow.add_edge("generate_v1_patch", "initial_verification")

    # Conditional route to Debate Setup
    workflow.add_conditional_edges("initial_verification", route_after_v1, {
        "end": END, 
        "debate_panel": "debate_panel"
    })
    
    # ==========================================
    # 4. INNER LOOP PARALLEL ROUTING
    # ==========================================
    # Fan-Out 1: Both debaters generate arguments simultaneously
    workflow.add_edge("debate_panel", "generate_dynamic_arg")
    workflow.add_edge("debate_panel", "generate_static_arg")
    
    # Fan-In 1: Wait for BOTH arguments to finish before exchanging
    workflow.add_edge("generate_dynamic_arg", "exchange_arguments")
    workflow.add_edge("generate_static_arg", "exchange_arguments")
    
    # Fan-Out 2: Both debaters read the exchanged state and write rebuttals
    workflow.add_edge("exchange_arguments", "generate_dynamic_rebuttal")
    workflow.add_edge("exchange_arguments", "generate_static_rebuttal")
    
    # Fan-In 2: Wait for BOTH rebuttals before passing to the Judge
    workflow.add_edge("generate_dynamic_rebuttal", "judge_verdict")
    workflow.add_edge("generate_static_rebuttal", "judge_verdict")
    # ==========================================
    
    # 5. Judge to Refined Patch to Verification
    workflow.add_edge("judge_verdict", "generate_refined_patch")
    workflow.add_edge("generate_refined_patch", "verify_refined")
    
    workflow.add_conditional_edges("verify_refined", route_after_refined, {
        "end": END, 
        "pattern_selection": "pattern_selection", 
        "debate_panel": "debate_panel",
        "hard_stop": END
    })

    return workflow.compile(checkpointer=MemorySaver())

def draw_graph(app):
    file_name = "spade_graph.png"
# ==========================================
    # Generate Architecture Diagram
    # ==========================================
    print("\n--- Generating graph... ---")
    
    try:
        png_data = app.get_graph().draw_mermaid_png()
        with open(file_name, "wb") as f:
            f.write(png_data)
        print(f"Saved graph image to {file_name}")
    except Exception as e:
        print(f"Could not generate PNG (might require internet/httpx): {e}")