from src.utils.logger import log, get_loop_info
import logging
from src.core.state import SpadeState, PatchCandidate
from config.settings import M_INNER_LOOPS, V_PATIENCE, N_OUTER_LOOPS

agent_name = "Test_Agent"

def _execute_and_evaluate(patch: PatchCandidate, state: SpadeState) -> PatchCandidate:
    """
    Shared helper to apply a patch and run its evaluation.
    In a real system, this would trigger a Docker container or subprocess to run tests.
    """
    log(f"Evaluating patch {patch.id} (v{patch.version})...", agent_name)
    
    # MOCK LOGIC: In a real system, evaluation would populate patch.evaluation
    if patch.id == "mock_a_pass":
        patch.status = "passed"
    else:
        patch.status = "failed"
        patch.execution_trace = "AssertionError: Traceback (most recent call last): ..."
        
    return patch

def verify_v1(state: SpadeState):
    """
    Initial verification for the entire v1 pool.
    """
    loop_info_str, _ = get_loop_info(state, include_inner=False)
    log(f"{loop_info_str} Initial patch verification (v1 pool)...", agent_name)
    
    v1_patches = state.get("v1_patches", [])
    any_passed = False
    
    for patch in v1_patches:
        if patch.status != "pending":
            continue

        _execute_and_evaluate(patch, state)
        if patch.status == "passed":
            any_passed = True
            log(f"Patch {patch.id} PASSED v1 verification!", agent_name)
            break 
            
    if any_passed:
        return {"resolution_status": "resolved"}
    
    log("All v1 candidates failed. Moving to debate panel.", agent_name)
    return {"resolution_status": "v1_failed"}

def verify_refined(state: SpadeState):
    """
    Verification for the latest refined patch (v2, v3, etc.)
    """
    refined_patches = state.get("refined_patches", [])
    if not refined_patches:
        log("No refined patch found to verify.", agent_name, level=logging.ERROR)
        return {"resolution_status": "error"}

    patch = refined_patches[-1]
    
    loop_info_str, _ = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Refined patch verification (v{patch.version})...", agent_name)
    
    _execute_and_evaluate(patch, state)
    
    if patch.status == "passed":
        log(f">>> v{patch.version} PATCH PASSED! <<<", agent_name)
        return {"resolution_status": "resolved"}
    
    # Otherwise, trigger the fallback policy
    return _handle_fallback(state, patch.version, patch)

def _handle_fallback(state: SpadeState, current_v: int, failed_patch: PatchCandidate):
    """
    Policy Method: Records the test failure and decides the next step.
    """
    failed_trace_log = f"v{current_v} ({failed_patch.id}) Failed: {failed_patch.execution_trace[:50]}..."
    
    curr_m = state.get("inner_loop_count", 1)
    curr_n = state.get("outer_loop_count", 1)

    # Case 1: Patience left -> Refine same winner (v+1)
    # V_PATIENCE is the MAX version allowed for a lineage.
    # If current_v < V_PATIENCE, we can still refine to current_v + 1.
    if current_v < V_PATIENCE:
        next_v = current_v + 1
        log(f"Patch v{current_v} failed. Iteratively refining to v{next_v} (Version {next_v}/{V_PATIENCE}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": f"v{current_v}_failed", 
            "current_patch_version": next_v,
            "failed_traces": [failed_trace_log]
        }

    # Case 2: Patience hit (current_v == V_PATIENCE), try next winner?
    # Switch to a new winner (M+1, v=1), new inner loop
    if curr_m < M_INNER_LOOPS:
        log(f"V_PATIENCE={V_PATIENCE} REACHED for winner {failed_patch.origin_v1_id}. "
            f"Backtracking to pick a NEW winner (Attempt {curr_m + 1}/{M_INNER_LOOPS}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": f"v{current_v}_failed", 
            "inner_loop_count": curr_m + 1,
            "current_patch_version": 1, # Reset to 1 to signal new winner selection
            "failed_traces": [failed_trace_log]
        }

    # Case 3: Inner loops hit, try next patterns?
    # Reset to new patterns (N+1, M=1, v=1), new outer loop
    if curr_n < N_OUTER_LOOPS:
        log(f"INNER-LOOP-LIMIT M={M_INNER_LOOPS} REACHED. Resetting to Pattern Selection, preparing for N={curr_n + 1}\n", agent_name, level=logging.WARNING)
        return {
            "resolution_status": f"N{curr_n}_failed", 
            "inner_loop_count": 1, # Reset M
            "outer_loop_count": curr_n + 1, # Increment N
            "current_patch_version": 1, # Reset v
            "failed_traces": [failed_trace_log]
        }

    # Case 4: All limits hit -> Hard Stop
    log(f"MAX LIMITS REACHED (N={curr_n}/{N_OUTER_LOOPS}, M={curr_m}/{M_INNER_LOOPS}). Hard stop.", agent_name, level=logging.ERROR)
    return {
        "resolution_status": "failed",
        # Keep last values for logging
        "current_patch_version": current_v,
        "inner_loop_count": curr_m,
        "outer_loop_count": curr_n,
        "failed_traces": [failed_trace_log]
    }
