from src.utils.logger import log
from src.core.state import SpadeState
from src.evaluation.swe_bench_lite_utils import run_evaluation_with_no_patch, cleanup_logs_and_results_for_run

agent_name = "Reproduction"


def run(state: SpadeState):
    log(f"Starting reproduction agent...", agent_name)
    run_id = f"{state['thread_id']}_reproduction_check"
    bug_id = state["bug_context"].bug_id

    log(f"Running reproduction check for Bug ID: {bug_id} with Run ID: {run_id}", caller=agent_name)

    try:
        # Run evaluation with no patch to confirm the bug is reproducible
        evaluation_result = run_evaluation_with_no_patch(
            instance_id=bug_id,
            run_id=run_id
        )
        
        if not evaluation_result.evaluation_ran_successfully:
            log(f"Reproduction failed: Evaluation did not run successfully. Error: {evaluation_result.evaluation_error_message}", caller=agent_name)
            return {"success": False, "error_trace": evaluation_result.evaluation_error_message, "execution_logs": ["Reproduction failed: Evaluation did not run successfully."]}

        if evaluation_result.bug_resolved:
            log(f"Reproduction failed: Bug appears to be resolved without any patch. Check the test environment and test cases.", caller=agent_name)
            return {"success": False, "error_trace": "Bug appears to be resolved without any patch", "execution_logs": ["Reproduction failed: Bug appears to be resolved without any patch."]}

        log(f"Reproduction successful: Bug is reproducible and test environment is working as expected.", caller=agent_name)
        
        state["reproduction_evaluation_result"] = evaluation_result # Store the evaluation result in the state for future reference

        cleanup_logs_and_results_for_run(run_id=run_id) # Clean up logs and results to save space, since we have the evaluation result stored in the state

        return {"success": True, "execution_logs": ["Reproduction successful: Bug is reproducible. Look into ``reproduction_evaluation_result`` in the state for details."]}

    except Exception as e:
        log(f"Reproduction captured an exception: {str(e)}", caller=agent_name)
        return {"success": False, "error_trace": str(e), "execution_logs": [f"Reproduction captured an exception: {str(e)}"]}
