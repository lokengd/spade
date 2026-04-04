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
    loop_info_str, _ = get_loop_info(state, include_inner=True)

    evaluation_result = _run_evaluation_on_patch(bug_id, run_id, patch.code_diff)
    
    log(f"{loop_info_str} evaluation_result: {evaluation_result}", agent_name, level=logging.DEBUG)

    if state.get("v1_patches_evaluation_result") is None:
        state["v1_patches_evaluation_result"] = []

    state["v1_patches_evaluation_result"].append(evaluation_result) # Store each evaluation result in the state for future reference

    if evaluation_result.bug_resolved:
        log(f"{loop_info_str} >>> PATCH {patch.id} Resolved Issue <<<", caller=agent_name)
        patch.status = "passed"
    else:
        patch.status = "failed"
        log(f"{loop_info_str} PATCH {patch.id} failed to resolve the issue.", caller=agent_name)
        
    return patch


def _update_patch_status(patch: PatchCandidate, evaluation_result: EvaluationResult, loop_info_str: str) -> PatchCandidate:
    log(f"{loop_info_str} Evaluating patch {patch.id} (v{patch.version}, {patch.pattern})...", agent_name)
    
    # log(f"{loop_info_str} evaluation_result: {evaluation_result}", agent_name, level=logging.DEBUG)

    if evaluation_result.bug_resolved:
        log(f"{loop_info_str} >>> PATCH {patch.id} Resolved Issue <<<", caller=agent_name)
        patch.status = "passed"
    else:
        patch.status = "failed"
        log(f"{loop_info_str} PATCH {patch.id} failed to resolve the issue.", caller=agent_name)
        
    return patch


def verify_v1(state: SpadeState):
    """
    Initial verification for the entire v1 pool.
    """
    loop_info_str, _ = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Initial patch verification (v1 pool)...", agent_name)
    
    run_id = state.get("thread_id")
    v1_patches = state.get("v1_patches", [])
    any_passed = False

    v1_patches = [patch for patch in v1_patches if patch.status == "pending"]
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

        patch = _update_patch_status(patch, evaluation_results[index], loop_info_str)

        # Explicitly check for passed status when updating the DB
        is_passed = (patch.status == "passed")
        db_logger.update_patch(patch.id, tests_passed=is_passed)

        if is_passed:
            any_passed = True
            log(f"{loop_info_str} Patch {patch.id} PASSED v1 verification!", agent_name)
            
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
    else:
        log(f"{loop_info_str} All v1 candidates failed.", agent_name)
        return {"resolution_status": ["v1_failed"]}


def verify_refined(state: SpadeState):
    """
    Verification for the latest refined patch (v2, v3, etc.)
    """
    loop_info_str, _ = get_loop_info(state, include_inner=True)
    refined_patches = state.get("refined_patches", [])
    if not refined_patches:
        log(f"{loop_info_str} No refined patch found to verify.", agent_name, level=logging.ERROR)
        return {"resolution_status": ["test_agent_failed"]}

    run_id = state.get("thread_id")
    bug_id = state["bug_context"].bug_id
    # patch = refined_patches[-1]
    patch = next((p for p in reversed(refined_patches) if p.bug_id == bug_id), None)

    if patch is None:
        # handle missing case
        log(f"{loop_info_str} No matching refined patch found for bug_id {bug_id}.", agent_name, level=logging.ERROR)
        return {"resolution_status": ["test_agent_failed"]}
    
    log(f"{loop_info_str} Refined patch verification ({patch.id}) or bug_id {bug_id}...", agent_name)
    
    patch = _execute_and_evaluate(patch, state)

    # Explicitly check for passed status when updating the DB
    is_passed = (patch.status == "passed")
    db_logger.update_patch(patch.id, tests_passed=is_passed)

    if is_passed:
        log(f"{loop_info_str} >>> v{patch.id} PATCH PASSED! <<<", agent_name)
        if run_id:
            db_logger.update_repair_run(
                run_id=run_id,
                fl_match=True, # Assuming FL success if fix found
                is_resolved=True,
                status="success"
            )
        return {"resolution_status": ["resolved"]}
    
    # Otherwise, return failure status and let the orchestrator handle the fallback policy
    return {
        "resolution_status": [f"v{patch.version}_failed"]
    }
