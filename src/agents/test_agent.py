import logging
from src.core.state import SpadeState, PatchCandidate, EvaluationResult
from src.core import settings
from src.utils.logger import log, get_loop_info
from src.utils.db_logger import db_logger
from src.evaluation.swe_bench_lite_utils import run_evaluation_on_instance, cleanup_logs_and_results_for_run, run_evaluation_on_instance_in_parallel

agent_name = "Test_Agent"


def _run_evaluation_on_patch(bug_id: str, run_id: str, patch_code_diff: str) -> EvaluationResult:
    """
    Trigger a Docker container to run tests.
    """
    try:
        evaluation_result = run_evaluation_on_instance(
            instance_id=bug_id,
            run_id=run_id,
            patch=patch_code_diff
        )

        if not evaluation_result.evaluation_ran_successfully:
            log(f"Evaluation did not run successfully for patch. Error: {evaluation_result.evaluation_error_message}", caller=agent_name)
        
        cleanup_logs_and_results_for_run(run_id=run_id) # Clean up logs and results to save space, since we have the evaluation result stored in the state

        return evaluation_result

    except Exception as e:
        log(f"Evaluation captured an exception for patch: {str(e)}", caller=agent_name, level=logging.ERROR)
        return EvaluationResult(evaluation_ran_successfully=False, bug_resolved=False, evaluation_error_message=str(e))


def _execute_and_evaluate(patch: PatchCandidate, state: SpadeState) -> PatchCandidate:
    log(f"Evaluating patch {patch.id} (v{patch.version}, {patch.pattern})...", agent_name)
    
    bug_id = state["bug_context"].bug_id
    run_id = state.get("thread_id")

    evaluation_result = _run_evaluation_on_patch(bug_id, run_id, patch.code_diff)
    
    log(f"evaluation_result: {evaluation_result}", agent_name, level=logging.DEBUG)

    if state.get("v1_patches_evaluation_result") is None:
        state["v1_patches_evaluation_result"] = []

    state["v1_patches_evaluation_result"].append(evaluation_result) # Store each evaluation result in the state for future reference

    if evaluation_result.bug_resolved:
        log(f">>> v1 PATCH {patch.id} Resolved Issue <<<", caller=agent_name)
        patch.status = "passed"
    else:
        patch.status = "failed"
        log(f"v1 PATCH {patch.id} failed to resolve the issue.", caller=agent_name)
        
    return patch


def _update_patch_status(patch: PatchCandidate, evaluation_result: EvaluationResult) -> PatchCandidate:
    log(f"Evaluating patch {patch.id} (v{patch.version}, {patch.pattern})...", agent_name)
    
    log(f"evaluation_result: {evaluation_result}", agent_name, level=logging.DEBUG)

    if evaluation_result.bug_resolved:
        log(f">>> v1 PATCH {patch.id} Resolved Issue <<<", caller=agent_name)
        patch.status = "passed"
    else:
        patch.status = "failed"
        log(f"v1 PATCH {patch.id} failed to resolve the issue.", caller=agent_name)
        
    return patch


def verify_v1(state: SpadeState):
    """
    Initial verification for the entire v1 pool.
    """
    loop_info_str, _ = get_loop_info(state, include_inner=False)
    log(f"{loop_info_str} Initial patch verification (v1 pool)...", agent_name)
    
    run_id = state.get("thread_id")
    v1_patches = state.get("v1_patches", [])
    any_passed = False

    v1_patches_code_diff = [patch.code_diff for patch in v1_patches]
    evaluation_results = run_evaluation_on_instance_in_parallel(
        instance_id=state["bug_context"].bug_id,
        run_id=run_id,
        patches=v1_patches_code_diff
    )

    if state.get("v1_patches_evaluation_result") is None:
        state["v1_patches_evaluation_result"] = []

    state["v1_patches_evaluation_result"].extend(evaluation_results)
    
    for index, patch in enumerate(v1_patches):
        if patch.status != "pending":
            continue

        patch = _update_patch_status(patch, evaluation_results[index])

        # Explicitly check for passed status when updating the DB
        is_passed = (patch.status == "passed")
        db_logger.update_patch(patch.id, tests_passed=is_passed)

        if is_passed:
            any_passed = True
            log(f"Patch {patch.id} PASSED v1 verification!", agent_name)
            
            if run_id:
                # Update repair run status
                db_logger.update_repair_run(
                    run_id=run_id,
                    fl_match=True, # Assuming FL success if fix found
                    is_resolved=True,
                    status="success"
                )
            break 
            
    if any_passed:
        return {"resolution_status": ["resolved"]}
    
    if settings.M_INNER_LOOPS == 0:
        log("All v1 candidates failed. M=0: Skipping debate loop.", agent_name)
        curr_n = state.get("outer_loop_count", 1)
        if curr_n < settings.N_OUTER_LOOPS:
            log(f"M=0: Preparing for next Outer Loop (N={curr_n + 1}).", agent_name)
            return {
                "resolution_status": ["v1_failed"],
                "outer_loop_count": curr_n + 1,
                "inner_loop_count": 1,
                "current_patch_version": 1
            }
        else:
            log(f"M=0: All outer loops exhausted (N={curr_n}/{settings.N_OUTER_LOOPS}).", agent_name)
            return {"resolution_status": ["hit_max_limit"]}

    log("All v1 candidates failed. Moving to debate panel.", agent_name)
    return {"resolution_status": ["v1_failed"]}


def verify_refined(state: SpadeState):
    """
    Verification for the latest refined patch (v2, v3, etc.)
    """
    refined_patches = state.get("refined_patches", [])
    if not refined_patches:
        log("No refined patch found to verify.", agent_name, level=logging.ERROR)
        return {"resolution_status": ["test_agent_failed"]}

    patch = refined_patches[-1]
    run_id = state.get("thread_id")
    
    loop_info_str, _ = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Refined patch verification (v{patch.version})...", agent_name)
    
    patch = _execute_and_evaluate(patch, state)

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
        return {"resolution_status": ["resolved"]}
    
    # Otherwise, trigger the fallback policy
    return _handle_fallback(state, patch.version, patch)


def _handle_fallback(state: SpadeState, current_v: int, failed_patch: PatchCandidate):
    """
    Policy Method: Records the test failure and decides the next step.
    """
    failed_trace_log = failed_patch.execution_trace
    run_id = state.get("thread_id")

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
        log(f"Patch v{current_v} failed. Iteratively refining to v{next_v} (Version {next_v}/{settings.V_PATIENCE}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status(f"v{current_v}_failed")], 
            "current_patch_version": next_v,
            "failed_traces": [failed_trace_log]
        }

    # Case 2: Patience hit (current_v == V_PATIENCE), try next winner?
    if curr_m < settings.M_INNER_LOOPS:
        log(f"V_PATIENCE={settings.V_PATIENCE} REACHED for winner {failed_patch.origin_v1_id}. "
            f"Backtracking to pick a NEW winner (Attempt {curr_m + 1}/{settings.M_INNER_LOOPS}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status(f"v{current_v}_failed")], 
            "inner_loop_count": curr_m + 1,
            "current_patch_version": 1, 
            "failed_traces": [failed_trace_log]
        }

    # Case 3: Inner loops hit, try next patterns? hard reset
    if curr_n < settings.N_OUTER_LOOPS:
        log(f"INNER-LOOP-LIMIT M={settings.M_INNER_LOOPS} REACHED. Hard reset to Pattern Selection, preparing for N={curr_n + 1}\n", agent_name, level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status(f"N{curr_n}_failed")], 
            "inner_loop_count": 1, # Reset M
            "outer_loop_count": curr_n + 1, # Increment N
            "current_patch_version": 1, # Reset v
            "failed_traces": [failed_trace_log]
        }

    # Case 4: All limits hit -> Hard Stop
    log(f"MAX LIMITS REACHED (N={curr_n}/{settings.N_OUTER_LOOPS}, M={curr_m}/{settings.M_INNER_LOOPS}). Hard stop.", agent_name, level=logging.WARNING)
    return {
        "resolution_status": [_update_db_status("hit_max_limit")], 
        "current_patch_version": current_v,
        "inner_loop_count": curr_m,
        "outer_loop_count": curr_n,
        "failed_traces": [failed_trace_log]
    }
