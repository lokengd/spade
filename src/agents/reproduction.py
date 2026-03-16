from src.utils.logger import log
from src.core.state import SpadeState
from src.evaluation.swe_bench_lite_utils import run_evaluation_with_no_patch, cleanup_logs_and_results_for_run
from src.utils.db_logger import db_logger

agent_name = "Reproduction"

def run(state: SpadeState):
    log(f"Starting reproduction agent...", agent_name)
    bug_id = state["bug_context"].bug_id
    eval_run_id = f"{state['thread_id']}_reproduction_check"

    log(f"Running reproduction check for Bug ID: {bug_id} with evaluation Run ID: {eval_run_id}", caller=agent_name)

    try:
        # Run evaluation with no patch to confirm the bug is reproducible
        evaluation_result = run_evaluation_with_no_patch(
            instance_id=bug_id,
            run_id=eval_run_id
        )
        
        if not evaluation_result.evaluation_ran_successfully:
            log(f"Reproduction failed: Evaluation did not run successfully. Error: {evaluation_result.evaluation_error_message}", caller=agent_name)
            return {
                "resolution_status": "evaluation_failed", # TODO complete the logic at graph.py
            }
        if evaluation_result.bug_resolved:
            log(f"Reproduction failed: Bug appears to be resolved without any patch. Check the test environment and test cases.", caller=agent_name)
            return {
                "resolution_status": "evaluation_failed",
            }

        log(f"Reproduction successful: Bug is reproducible and test environment is working as expected.", caller=agent_name)
        
        state["reproduction_evaluation_result"] = evaluation_result # Store the evaluation result in the state for future reference

        cleanup_logs_and_results_for_run(run_id=eval_run_id) # Clean up logs and results to save space, since we have the evaluation result stored in the state

        bug_context = state["bug_context"]
        bug_context.error_trace = evaluation_result.test_output
        return {
            "bug_context": bug_context,
        }
    
    except Exception as e:
        log(f"Reproduction captured an exception: {str(e)}", caller=agent_name)
        raise