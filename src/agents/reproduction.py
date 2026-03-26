from src.utils.logger import log
from src.core.state import SpadeState
from src.evaluation.swe_bench_lite_utils import run_evaluation_with_no_patch, cleanup_logs_and_results_for_run
from src.utils.db_logger import db_logger
import os
import logging
from pathlib import Path


agent_name = "Reproduction"


_ERROR_TRACE_OF_INSTANCES_DIR = "error_trace_of_instances"


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[2]


def _read_error_trace_of_instance_from_file(instance_id: str) -> str | None:
    trace_file = _repo_root() / _ERROR_TRACE_OF_INSTANCES_DIR / f"{instance_id}.txt"

    if os.path.exists(trace_file):
        log(f"Reading error trace for instance {instance_id} from {trace_file}", caller=agent_name)
        with open(trace_file, "r") as f:
            return f.read()
    else:
        log(f"No error trace file found for instance {instance_id} at {trace_file}", caller=agent_name, level=logging.WARNING)
        return None


def run(state: SpadeState):
    log(f"Starting reproduction agent...", agent_name)
    run_id = state.get("thread_id")
    bug_context = state["bug_context"]
    bug_id = bug_context.bug_id

    log(f"Running reproduction check for Bug ID: {bug_id} with Run ID: {run_id}", caller=agent_name)

    try:
        # Run evaluation with no patch to confirm the bug is reproducible
        evaluation_result = run_evaluation_with_no_patch(
            instance_id=bug_id,
            run_id=run_id
        )

        if not evaluation_result.evaluation_ran_successfully:
            log(f"Reproduction failed: Evaluation did not run successfully. Error: {evaluation_result.evaluation_error_message}", caller=agent_name)
            return {
                "resolution_status": ["reproduction_failed"],
                "reproduction_evaluation_result": evaluation_result
            }

        if evaluation_result.bug_resolved:
            log(f"Reproduction failed: Bug appears to be resolved without any patch. Check the test environment and test cases.", caller=agent_name)
            return {
                "resolution_status": ["reproduction_failed"],
                "reproduction_evaluation_result": evaluation_result
            }

        log(f"Reproduction successful: Bug is reproducible and test environment is working as expected.", caller=agent_name)

        cleanup_logs_and_results_for_run(run_id=run_id) # Clean up logs and results to save space

        _pre_processed_error_trace = _read_error_trace_of_instance_from_file(bug_id)

        if _pre_processed_error_trace:
            log(f"Using pre-processed error trace for instance {bug_id} from file.", caller=agent_name)
            evaluation_result.test_output = _pre_processed_error_trace
        else:
            log(f"No pre-processed error trace found for instance {bug_id}. Using error trace from evaluation result.", caller=agent_name)

        bug_context.error_trace = evaluation_result.test_output

        # TEMP TEST - retrive pre-run error trace to speed up 
        # SKIP error trace 
        # trace_file = f"fl_results/swe_bench_lite_gold_patch/astropy__astropy/{bug_id}_error_trace.txt"
        # if os.path.exists(trace_file):
        #     log(f"TEMP FIX: Reading error trace from {trace_file}", caller=agent_name)
        #     with open(trace_file, "r") as f:
        #         test_output = f.read()
        #         bug_context.error_trace = test_output

        return {
            "bug_context": bug_context,
            "reproduction_evaluation_result": evaluation_result
        }

    except Exception as e:
        log(f"Reproduction captured an exception: {str(e)}", caller=agent_name, level=logging.ERROR)
        return {
            "resolution_status": ["reproduction_failed"],
        }
