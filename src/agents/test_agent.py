from src.utils.logger import log
import logging
from src.core.state import EvaluationResult, SpadeState, get_loop_info
from config.settings import M_INNER_LOOPS, V_PATIENCE
from src.evaluation.swe_bench_lite_utils import run_evaluation_on_instance, cleanup_logs_and_results_for_run


agent_name = "Test Agent"


def verify_v1(state: SpadeState):
    log(f"Starting v1 patch verification...", agent_name)

    instance_id = state["bug_context"].bug_id

    for patch in state["v1_patches"]:
        log(f"Testing v1 patch candidate: {patch['id']}...", caller=agent_name)
        
        run_id = f"{state['thread_id']}_v1_patch_{patch['id']}"
        patch = patch['code_diff']

        evaluation_result = _run_evaluation_on_patch(instance_id, run_id, patch)

        state["v1_patches_evaluation_result"].append(evaluation_result) # Store each evaluation result in the state for future reference

        if evaluation_result.bug_resolved:
            log(f">>> v1 PATCH {patch['id']} Resolved Issue <<<", caller=agent_name)
            patch['status'] = 'passed'
            return {"bug_resolved": True, "patch_id": patch['id']}
        
        patch['status'] = 'failed'
        log(f"v1 PATCH {patch['id']} failed to resolve the issue.", caller=agent_name, level=logging.INFO)

    return {"bug_resolved": False, "patch_id": None}


def verify_refined(state: SpadeState):
    log(f"Starting refined patch verification...", agent_name)

    instance_id = state["bug_context"].bug_id
    patch = state.get("current_refined_patch").code_diff
    run_id = f"{state['thread_id']}_refined_patch_{state.get("current_refined_patch").id}"

    evaluation_result = _run_evaluation_on_patch(instance_id, run_id, patch)
    state["refined_patch_evaluation_result"] = evaluation_result # Store the evaluation result in the state for future reference

    if evaluation_result.bug_resolved:
        log(f">>> Refined PATCH Resolved Issue <<<", caller=agent_name)
        state.get("current_refined_patch").status = 'passed'
        return {"bug_resolved": True, "patch_id": state.get("current_refined_patch").id}

    state.get("current_refined_patch").status = 'failed'
    log(f"Refined PATCH failed to resolve the issue.", caller=agent_name, level=logging.INFO)

    return {"bug_resolved": False, "patch_id": None}


def _run_evaluation_on_patch(instance_id: str, run_id: str, patch: str) -> EvaluationResult:
    try:
        evaluation_result = run_evaluation_on_instance(
            instance_id=instance_id,
            run_id=run_id,
            patch=patch
        )

        if not evaluation_result.evaluation_ran_successfully:
            log(f"Evaluation did not run successfully for patch. Error: {evaluation_result.evaluation_error_message}", caller=agent_name)
        
        cleanup_logs_and_results_for_run(run_id=run_id) # Clean up logs and results to save space, since we have the evaluation result stored in the state

        return evaluation_result

    except Exception as e:
        log(f"Evaluation captured an exception for patch: {str(e)}", caller=agent_name, level=logging.ERROR)
        return EvaluationResult(evaluation_ran_successfully=False, bug_resolved=False, evaluation_error_message=str(e))


# Initial verification for v1 patch candidates
def old_verify_v1(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=False)
    log(f"{loop_info} Initial patch verification (v1)...", agent_name)
    # Assumed all v1 patches fail, so we remain in progress to trigger the debate
    return {"resolution_status": "in_progress"}

def old_verify_refined(state: SpadeState):
    patch = state.get("current_refined_patch")
    current_v = state.get("current_patch_version", 2)
    
    loop_info = get_loop_info(state, include_inner=True)
    log(f"{loop_info} Patch verification (v{current_v})...", agent_name)
    
    if patch is not None and patch.get("id") == "mock_a_pass": 
        log(f">>> v{current_v} PATCH PASSED FAIL_TO_PASS! <<<", agent_name)
        return {"resolution_status": "resolved"}
    
    # Otherwise, trigger the fallback policy
    return _old_handle_fallback(state, current_v)

def _old_handle_fallback(state: SpadeState, current_v: int):
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
        log(f"INNER-LOOP-LIMIT M={M_INNER_LOOPS} REACHED. Restart Outer Loop, preparing for N={next_n}\n", agent_name, level=logging.WARNING)
        return {
            "resolution_status": "in_progress", 
            "inner_loop_count": new_inner_count, 
            "outer_loop_count": next_n,
            "current_patch_version": current_v,  
            "failed_traces": [failed_trace_log]
        }
        
    # Case 2: Exhausted V Patience -> Backtracking to re-select from v1 pool
    elif current_v >= V_PATIENCE:
        log(f"V_PATIENCE={V_PATIENCE} REACHED. Backtracking to pattern selection for new v1 candidates.\n", agent_name, level=logging.WARNING)
        return {
            "resolution_status": "in_progress", 
            "inner_loop_count": new_inner_count,
            "current_patch_version": 1, # Signal backtracking for the debate panel
            "failed_traces": [failed_trace_log]
        }
        
    # Case 3: Have Patience & Loops left -> Iterative Refinement
    log(f"Patch v{current_v} failed. Iteratively refining to v{current_v + 1} (Inner Attempt {new_inner_count}/{M_INNER_LOOPS}).", agent_name, level=logging.WARNING)
    return {
        "resolution_status": "in_progress", 
        "inner_loop_count": new_inner_count,
        "current_patch_version": current_v + 1,
        "failed_traces": [failed_trace_log]
    }
