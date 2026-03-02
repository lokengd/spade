import logging
from src.core.state import SpadeState, get_loop_info
from config.settings import M_INNER_LOOPS, V_PATIENCE

logger = logging.getLogger(__name__)

# Initial verification for v1 patch candidates
def verify_v1(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=False)
    logger.info(f"[Test Agent] {loop_info} Initial patch verification (v1)...")
    # Assumed all v1 patches fail, so we remain in progress to trigger the debate
    return {"resolution_status": "in_progress"}

def verify_refined(state: SpadeState):
    patch = state.get("current_refined_patch")
    current_v = state.get("current_patch_version", 2)
    
    loop_info = get_loop_info(state, include_inner=True)
    logger.info(f"[Test Agent] {loop_info} Patch verification (v{current_v})...")
    
    if patch is not None and patch.get("id") == "mock_a_pass": 
        logger.info(f">>> v{current_v} PATCH PASSED FAIL_TO_PASS! <<<")
        return {"resolution_status": "resolved"}
    
    # Otherwise, trigger the fallback policy
    return _handle_fallback(state, current_v)

def _handle_fallback(state: SpadeState, current_v: int):
    """
    Policy Method: Records the test failure and increments counters.
    Leaves the routing decisions to `route_after_refined`.
    """
    new_inner_count = state.get("inner_loop_count", 1) + 1
    failed_trace_log = f"v{current_v} Failed: AssertionError"
    
    # Case 1: Exhausted M Inner Loops 
    if new_inner_count >= M_INNER_LOOPS:
        # Increment the outer loop (N)
        next_n = state.get("outer_loop_count", 1) + 1
        logger.warning(f"INNER-LOOP-LIMIT M={M_INNER_LOOPS} REACHED. Restart Outer Loop, preparing for N={next_n}\n")
        return {
            "resolution_status": "in_progress", 
            "inner_loop_count": new_inner_count, 
            "outer_loop_count": next_n,
            "current_patch_version": current_v,  
            "failed_traces": [failed_trace_log]
        }
        
    # Case 2: Exhausted V Patience -> Backtracking to re-select from v1 pool
    elif current_v >= V_PATIENCE:
        logger.warning(f"V_PATIENCE={V_PATIENCE} REACHED. Backtracking at M:{new_inner_count}\n")
        return {
            "resolution_status": "in_progress", 
            "inner_loop_count": new_inner_count,
            "current_patch_version": 1, # Signal backtracking for the debate panel
            "failed_traces": [failed_trace_log]
        }
        
    # Case 3: Have Patience & Loops left -> Iterative Refinement
    logger.warning(f">>> FAILED. Iteratively refining to v{current_v + 1} (Inner Attempt {new_inner_count}/{M_INNER_LOOPS}). <<<")
    return {
        "resolution_status": "in_progress", 
        "inner_loop_count": new_inner_count,
        "current_patch_version": current_v + 1,
        "failed_traces": [failed_trace_log]
    }