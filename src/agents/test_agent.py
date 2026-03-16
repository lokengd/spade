from src.utils.logger import log, get_loop_info
import logging
from src.core.state import EvaluationResult, SpadeState, get_loop_info, SpadeState, PatchCandidate
from config.settings import M_INNER_LOOPS, V_PATIENCE
from src.evaluation.swe_bench_lite_utils import run_evaluation_on_instance, cleanup_logs_and_results_for_run
from src.core import settings
from src.utils.db_logger import db_logger


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
    log(f"Starting v1 patch verification...", agent_name)

    instance_id = state["bug_context"].bug_id

    for patch in state["v1_patches"]:
        log(f"Testing v1 patch candidate: {patch['id']}...", caller=agent_name)
        
        run_id = f"{state['thread_id']}_v1_patch_{patch['id']}"
        patch_code = patch['code_diff']

        evaluation_result = _run_evaluation_on_patch(instance_id, run_id, patch_code)

        if state.get("v1_patches_evaluation_result") is None:
            state["v1_patches_evaluation_result"] = []

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
    patch = state.get("current_refined_patch")
    patch_code = patch.code_diff
    run_id = f"{state['thread_id']}_refined_patch_{patch.id}"

    evaluation_result = _run_evaluation_on_patch(instance_id, run_id, patch_code)
    state["refined_patch_evaluation_result"] = evaluation_result # Store the evaluation result in the state for future reference

    if evaluation_result.bug_resolved:
        log(f">>> Refined PATCH Resolved Issue <<<", caller=agent_name)
        patch.status = 'passed'
        return {"bug_resolved": True, "patch_id": patch.id}

    patch.status = 'failed'
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
    
    _execute_and_evaluate(patch, state)
    
    # Explicitly check for passed status when updating the DB
    is_passed = (patch.status == "passed")
    db_logger.update_patch(patch.id, tests_passed=is_passed)

    if is_passed:
        log(f">>> v{patch.version} PATCH PASSED! <<<", agent_name)
        if run_id:
            db_logger.update_repair_run(
                run_id=run_id,
                fl_match=True,
                is_resolved=True,
                status="success"
            )
        return {"resolution_status": "resolved"}
    
    # Otherwise, trigger the fallback policy
    return _old_handle_fallback(state, current_v)

def _old_handle_fallback(state: SpadeState, current_v: int):
    """
    Policy Method: Records the test failure and decides the next step.
    """
    failed_trace_log = f"v{current_v} ({failed_patch.id}) Failed: {failed_patch.execution_trace[:50]}..."
    run_id = state.get("thread_id")
    
    curr_m = state.get("inner_loop_count", 1)
    curr_n = state.get("outer_loop_count", 1)

    # Case 1: Patience left -> Refine same winner (v+1)
    if current_v < settings.V_PATIENCE:
        next_v = current_v + 1
        log(f"Patch v{current_v} failed. Iteratively refining to v{next_v} (Version {next_v}/{settings.V_PATIENCE}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": f"v{current_v}_failed", 
            "current_patch_version": next_v,
            "failed_traces": [failed_trace_log]
        }

    # Case 2: Patience hit (current_v == V_PATIENCE), try next winner?
    if curr_m < settings.M_INNER_LOOPS:
        log(f"V_PATIENCE={settings.V_PATIENCE} REACHED for winner {failed_patch.origin_v1_id}. "
            f"Backtracking to pick a NEW winner (Attempt {curr_m + 1}/{settings.M_INNER_LOOPS}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": f"v{current_v}_failed", 
            "inner_loop_count": curr_m + 1,
            "current_patch_version": 1, 
            "failed_traces": [failed_trace_log]
        }

    # Case 3: Inner loops hit, try next patterns?
    if curr_n < settings.N_OUTER_LOOPS:
        log(f"INNER-LOOP-LIMIT M={settings.M_INNER_LOOPS} REACHED. Resetting to Pattern Selection, preparing for N={curr_n + 1}\n", agent_name, level=logging.WARNING)
        return {
            "resolution_status": f"N{curr_n}_failed", 
            "inner_loop_count": 1, # Reset M
            "outer_loop_count": curr_n + 1, # Increment N
            "current_patch_version": 1, # Reset v
            "failed_traces": [failed_trace_log]
        }

    # Case 4: All limits hit -> Hard Stop
    log(f"MAX LIMITS REACHED (N={curr_n}/{settings.N_OUTER_LOOPS}, M={curr_m}/{settings.M_INNER_LOOPS}). Hard stop.", agent_name, level=logging.ERROR)
    if run_id:
        db_logger.update_repair_run(
            run_id=run_id,
            fl_match=False, 
            is_resolved=False,
            status="failed"
        )
    return {
        "resolution_status": "failed",
        "current_patch_version": current_v,
        "inner_loop_count": curr_m,
        "outer_loop_count": curr_n,
        "failed_traces": [failed_trace_log]
    }
