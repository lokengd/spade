from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send
import logging
from typing import Optional, List, Any
from src.core.state import SpadeState, P_UNCONSTRAINED
from src.core import settings
from src.utils.logger import log, get_loop_info
from src.utils.db_logger import db_logger
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
    thread_id = state.get("thread_id")
    experiment_id = state.get("experiment_id")

    # Activate K agents
    if settings.K_PATTERNS > 0:
        for pattern in state.get("selected_patterns", [])[:settings.K_PATTERNS]:
            sends.append(Send("generate_v1_patch", {
                "active_pattern": pattern,
                "bug_context": state["bug_context"],
                "outer_loop_count": current_n,
                "inner_loop_count": current_m,
                "current_patch_version": current_v,
                "thread_id": thread_id,
                "experiment_id": experiment_id
            }))
        
    # Activate the +1 Unconstrained LLM agent
    sends.append(Send("generate_v1_patch", {
        "active_pattern": P_UNCONSTRAINED,
        "bug_context": state["bug_context"],
        "outer_loop_count": current_n,
        "inner_loop_count": current_m,
        "current_patch_version": current_v,
        "thread_id": thread_id,
        "experiment_id": experiment_id
    }))
    
    return sends

def check_status(state: dict, critical_statuses: list[str]) -> Optional[str]:
    statuses = state.get("resolution_status", [])
    # Check if the list has items AND if the very last (most recent) status    
    if statuses and statuses[-1] in critical_statuses:
        log(f"Status ({statuses[-1]}) hit!", caller="Orchestrator", level=logging.WARNING)
        return True
        
    return False

def route_after_fl(state: SpadeState):

    if check_status(state, ["patchgen_failed", "test_agent_failed"]):
        log(f"Agent error. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"

    if check_status(state, ["fl_failed"]):
        log("Fault Localization failed. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
    
    return "reproduction"

def route_after_reproduction(state: SpadeState):
    if check_status(state, ["reproduction_failed"]):
        log(f"Reproduction failed. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"

    if settings.K_PATTERNS == 0:
        log("K=0: Skipping Pattern Selection, proceeding to Unconstrained PatchGen.", "Orchestrator")
        return activate_patchgen_agents(state)
    
    return "pattern_selection"

def route_after_pattern_selection(state: SpadeState):
    if check_status(state, ["pattern_selection_failed"]):
        log("Pattern Selection failed. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
    return activate_patchgen_agents(state)

def route_after_judge(state: SpadeState):
    if check_status(state, ["judge_failed"]):
        curr_m = state.get("inner_loop_count", 1)
        curr_n = state.get("outer_loop_count", 1)
        
        # We need to look at the previous counters before the increment in Judge._handle_judge_failure
        # Actually, Judge returns the NEW counters. 
        # So we just check if it's still within limits.
        
        if curr_m > 1 and curr_m <= settings.M_INNER_LOOPS:
             log(f"Judge failed. Backtracking to pick a NEW winner (M={curr_m}).", "Orchestrator")
             return "debate_panel"
             
        if curr_n > 1 and curr_n <= settings.N_OUTER_LOOPS:
             log(f"Judge failed and M reached limit. Transitioning to new Outer Loop (N={curr_n}).", "Orchestrator")
             return "pattern_selection"

        log("Judge failed and all limits hit. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
        
    return "generate_refined_patch"

def route_after_v1(state: SpadeState):
    if check_status(state, ["resolved"]):
        return "end"
    
    if check_status(state, ["patchgen_failed"]):
        log("PatchGen failed. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
    
    if check_status(state, ["v1_failed"]):
        return "v1_fallback_policy"

    return "debate_panel"

def v1_fallback_policy(state: SpadeState):
    """
    Policy Method: Handles initial v1 failure.
    Decides whether to proceed to debate panel or transition to new outer loop (if M=0).
    """
    run_id = state.get("thread_id")
    loop_info_str, _ = get_loop_info(state, include_inner=False)

    # Inner helper to update the DB for the current scenario
    def _update_db_status(status: str = "failed"):
        if run_id:
            db_logger.update_repair_run(
                run_id=run_id,
                fl_match=None, 
                is_resolved=False,
                status=status
            )
        return status

    if settings.M_INNER_LOOPS == 0:
        curr_n = state.get("outer_loop_count", 1)
        if curr_n < settings.N_OUTER_LOOPS:
            log(f"{loop_info_str} All v1 failed. M=0: Transitioning to Outer Loop N={curr_n + 1}.", "Orchestrator", level=logging.WARNING)
            return {
                "resolution_status": [_update_db_status(f"N{curr_n}_failed")], 
                "inner_loop_count": 1, 
                "outer_loop_count": curr_n + 1, 
                "current_patch_version": 1
            }
        else:
            log(f"{loop_info_str} All v1 failed. M=0: All outer loops exhausted. Hard Stop.", "Orchestrator", level=logging.WARNING)
            return {"resolution_status": [_update_db_status("hit_max_limit")]}
    
    # If M > 0, we just continue with the current state (v1_failed is already in resolution_status)
    return {}

def route_after_v1_fallback(state: SpadeState):
    """
    Decides where to route after v1_fallback_policy.
    """
    if check_status(state, ["hit_max_limit"]):
        return "hard_stop"
        
    statuses = state.get("resolution_status", [])        
    if statuses and statuses[-1].startswith("N") and statuses[-1].endswith("_failed"):
        # Transitions to new outer loop: triggers reproduction/pattern_selection
        return route_after_reproduction(state)
        
    return "debate_panel"

def route_after_refined(state: SpadeState):
    # Success! Exit the graph.
    if check_status(state, ["resolved"]):
        return "end"
    
    loop_info_str, _ = get_loop_info(state, include_inner=False)
    if check_status(state, ["patchgen_failed", "test_agent_failed"]):
        log(f"{loop_info_str} Agent error. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
        
    # Check if it failed verification (v*_failed)
    statuses = state.get("resolution_status", [])
    if statuses and statuses[-1].startswith("v") and statuses[-1].endswith("_failed"):
         return "refined_fallback_policy"

    # Hard Stop check - if test_agent signaled failure or counters exceed limit
    if check_status(state, ["hit_max_limit"]) or state.get("outer_loop_count", 1) > settings.N_OUTER_LOOPS:        
        log(f"{loop_info_str} MAX LIMITS REACHED. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
        
    return "hard_stop"

def refined_fallback_policy(state: SpadeState):
    """
    Policy Method: Records the test failure for refined patches and decides the next step.
    """
    run_id = state.get("thread_id")
    loop_info_str, _ = get_loop_info(state, include_inner=True)

    refined_patches = state.get("refined_patches", [])
    if not refined_patches:
        log(f"{loop_info_str} No refined patches found in refined_fallback_policy.", caller="Orchestrator", level=logging.ERROR)
        return {"resolution_status": ["hit_max_limit"]} 
        
    failed_patch = refined_patches[-1]
    current_v = failed_patch.version
    failed_trace_log = failed_patch.execution_trace

    # Inner helper to update the DB for the current scenario
    def _update_db_status(status: str = "failed"):
        if run_id:
            db_logger.update_repair_run(
                run_id=run_id,
                fl_match=False, 
                is_resolved=False,
                status=status
            )
            return status
        else:
            return None  

    curr_m = state.get("inner_loop_count", 1)
    curr_n = state.get("outer_loop_count", 1)

    # Case 1: Patience left -> Refine same winner (v+1)
    if current_v < settings.V_PATIENCE:
        next_v = current_v + 1
        log(f"{loop_info_str} Patch v{current_v} failed. Iteratively refining to v{next_v} (Version {next_v}/{settings.V_PATIENCE}).", "Orchestrator", level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status(f"v{current_v}_failed")], 
            "current_patch_version": next_v,
            "failed_traces": [failed_trace_log]
        }

    # Case 2: Patience hit (current_v == V_PATIENCE), try next winner?
    if curr_m < settings.M_INNER_LOOPS:
        log(f"{loop_info_str} V_PATIENCE={settings.V_PATIENCE} REACHED for winner {failed_patch.origin_v1_id}. "
            f"Backtracking to pick a NEW winner (Attempt {curr_m + 1}/{settings.M_INNER_LOOPS}).", "Orchestrator", level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status(f"v{current_v}_failed")], 
            "inner_loop_count": curr_m + 1,
            "current_patch_version": 1, 
            "failed_traces": [failed_trace_log]
        }

    # Case 3: Inner loops hit, try next patterns? hard reset
    if curr_n < settings.N_OUTER_LOOPS:
        log(f"{loop_info_str} INNER-LOOP-LIMIT M={settings.M_INNER_LOOPS} REACHED. Hard reset to Pattern Selection, preparing for N={curr_n + 1}\n", "Orchestrator", level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status(f"N{curr_n}_failed")], 
            "inner_loop_count": 1, # Reset M
            "outer_loop_count": curr_n + 1, # Increment N
            "current_patch_version": 1, # Reset v
            "failed_traces": [failed_trace_log]
        }

    # Case 4: All limits hit -> Hard Stop
    log(f"{loop_info_str} MAX LIMITS REACHED (N={curr_n}/{settings.N_OUTER_LOOPS}, M={curr_m}/{settings.M_INNER_LOOPS}). Hard stop.", "Orchestrator", level=logging.WARNING)
    return {
        "resolution_status": [_update_db_status("hit_max_limit")], 
        "current_patch_version": current_v,
        "inner_loop_count": curr_m,
        "outer_loop_count": curr_n,
        "failed_traces": [failed_trace_log]
    }

def route_after_refined_fallback(state: SpadeState):
    """
    Checks the latest status after refined_fallback_policy to decide where to route next.
    """
    loop_info_str, _ = get_loop_info(state, include_inner=True)
    if check_status(state, ["hit_max_limit"]):
        log(f"{loop_info_str} MAX LIMITS REACHED. Hard Stop!", "Orchestrator", level=logging.WARNING)
        return "hard_stop"
        
    statuses = state.get("resolution_status", [])        
    if statuses and statuses[-1].startswith("N") and statuses[-1].endswith("_failed"):
        log(f"{loop_info_str} Dynamic failure ({statuses[-1]}). Transitioning to new Outer Loop (Pattern Selection).", caller="Orchestrator")
        return "pattern_selection"
        
    # Default to debate panel for Iterative Refinement (v+1) or Backtracking (M+1)
    return "debate_panel"


def build_graph():

    graph = StateGraph(SpadeState)

    # Add nodes
    graph.add_node("fl_ensemble", fl_ensemble.run)
    graph.add_node("reproduction", reproduction.run)
    graph.add_node("pattern_selection", pattern_selection.run)
    graph.add_node("generate_v1_patch", patchgen.generate_v1_patch)    
    graph.add_node("verify_v1", test_agent.verify_v1)
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
    graph.add_node("v1_fallback_policy", v1_fallback_policy)
    graph.add_node("refined_fallback_policy", refined_fallback_policy)

    # Add edges
    graph.add_edge(START, "fl_ensemble")
    
    # Conditional edge from fl_ensemble
    graph.add_conditional_edges(
        "fl_ensemble",
        route_after_fl,
        {
            "reproduction": "reproduction",
            "hard_stop": END
        }
    )
    
    # Conditional edge from reproduction
    graph.add_conditional_edges(
        "reproduction",
        route_after_reproduction,
        {
            "pattern_selection": "pattern_selection",
            "generate_v1_patch": "generate_v1_patch",
            "hard_stop": END
        }
    )

    # Fan-Out to K+1 PatchGen agents using the dynamic Send API
    graph.add_conditional_edges(
        "pattern_selection", 
        route_after_pattern_selection, 
        {
            "generate_v1_patch": "generate_v1_patch",
            "hard_stop": END
        }
    )
    # Fan-In: Wait for all K+1 patches, then go to verify_v1
    graph.add_edge("generate_v1_patch", "verify_v1")
    # Conditional route to Debate Setup
    graph.add_conditional_edges("verify_v1", route_after_v1, {
        "end": END, 
        "v1_fallback_policy": "v1_fallback_policy",
        "debate_panel": "debate_panel",
        "hard_stop": END
    })

    graph.add_conditional_edges("v1_fallback_policy", route_after_v1_fallback, {
        "pattern_selection": "pattern_selection",
        "generate_v1_patch": "generate_v1_patch", # If route_after_reproduction returns Send
        "debate_panel": "debate_panel",
        "hard_stop": END
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
    graph.add_conditional_edges(
        "judge_verdict",
        route_after_judge,
        {
            "generate_refined_patch": "generate_refined_patch",
            "hard_stop": END
        }
    )
    graph.add_edge("generate_refined_patch", "verify_refined")
    
    graph.add_conditional_edges("verify_refined", route_after_refined, {
        "end": END, 
        "refined_fallback_policy": "refined_fallback_policy",
        "hard_stop": END
    })

    graph.add_conditional_edges("refined_fallback_policy", route_after_refined_fallback, {
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
