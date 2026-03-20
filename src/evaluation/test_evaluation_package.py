"""Test script to validate the setup and functionality of SWE-bench for evaluation purposes."""

from src.evaluation.swe_bench_lite_utils import *
from src.evaluation.constants import NO_CHANGE_PATCH, VALIDATION_INSTANCE_ID

print("Starting SWE-bench setup validation...")

print("Checking if Docker is installed and running...")
assert check_docker_installed_and_running(), "Docker is not installed or running. Please install and start Docker to proceed."
print("Docker is installed and running. ✅")

print("Cloning and installing SWE-bench...")
assert clone_and_install_swe_bench(), "Failed to clone and install SWE-bench."
print("SWE-bench cloned and installed successfully. ✅")

print("Testing SWE-bench installation...")
assert test_installation(), "SWE-bench installation test failed."
print("SWE-bench installation test passed. ✅")

print("Get Validation Test Case Results...")
bug_results = is_bug_resolved(instance_id=VALIDATION_INSTANCE_ID, run_id=VALIDATION_RUN_ID, predictions_path=VALIDATION_PREDICTIONS_PATH)

assert bug_results["method_success"], f"Failed to get test case results: {bug_results.get('error')}"
assert bug_results.get("test_case_passed"), "Validation test case did not pass."

report_path = get_report_path(instance_id=VALIDATION_INSTANCE_ID, run_id=VALIDATION_RUN_ID, predictions_path=VALIDATION_PREDICTIONS_PATH)
assert report_path.exists() and report_path.is_file(), "Report file not found after validation run."

report_data = get_report_file(report_path)
assert report_data["method_success"], f"Failed to read report file: {report_data.get('error')}"

test_output_path = get_test_output_path(instance_id=VALIDATION_INSTANCE_ID, run_id=VALIDATION_RUN_ID, predictions_path=VALIDATION_PREDICTIONS_PATH)
assert test_output_path.exists() and test_output_path.is_file(), "Test output file not found after validation run."

test_output_data = get_test_output_file(test_output_path)
assert test_output_data["method_success"], f"Failed to read test output file: {test_output_data.get('error')}"
assert isinstance(test_output_data.get("test_output"), str), "Test output is empty after validation run."

test_case_results = get_test_case_results(report_data["report_data"])
assert test_case_results['bug_resolved'], "Bug was not resolved according to test case results."
assert test_case_results['pass_to_pass_success'], "PASS_TO_PASS test case did not pass."
assert test_case_results['fail_to_pass_success'], "FAIL_TO_PASS test case did not pass."
print("Validation test case passed successfully. ✅")

print("Cleaning up validation logs and results...")
assert cleanup_validation_logs_and_results(), "Failed to clean up logs and results after testing."
print("Logs and results cleaned up successfully. ✅")

print("Testing evaluation with no patch...")
INSTANCE_ID = VALIDATION_INSTANCE_ID
RUN_ID = "test_no_patch_run"

evaluation_result = run_evaluation_with_no_patch(instance_id=INSTANCE_ID, run_id=RUN_ID)
assert evaluation_result.evaluation_ran_successfully, f"Evaluation with no patch did not run successfully: {evaluation_result.evaluation_error_message}"
assert not evaluation_result.bug_resolved, "Bug should not be resolved when running evaluation with no patch."
# assert evaluation_result.test_output.split("\n")[0].__contains__("test process starts"), "Start Test output does not contain expected content."
# assert evaluation_result.test_output.split("\n")[-1].__contains__("tests finished:"), "End Test output does not contain expected content."
# assert evaluation_result.test_output.split("\n")[0].__contains__("==="), "Start Test output does not contain expected content."
print("Evaluation with no patch completed successfully. ✅")

print("Cleaning up logs and results for the run with no patch...")
assert cleanup_logs_and_results_for_run(run_id=RUN_ID), f"Failed to clean up logs and results for run {RUN_ID}."
print("Logs and results for no patch run cleaned up successfully. ✅")

print("Testing parallel evaluation with multiple no-change patches...")
EXAMPLE_PATCHES = [NO_CHANGE_PATCH] * 3  # Using the no-change patch as a placeholder for testing
INSTANCE_ID = VALIDATION_INSTANCE_ID
RUN_ID = "parallel_test_run"
evaluation_results = run_evaluation_on_instance_in_parallel(instance_id=INSTANCE_ID, run_id=RUN_ID, patches=EXAMPLE_PATCHES)

assert len(evaluation_results) == len(EXAMPLE_PATCHES), "Number of evaluation results does not match number of patches."
for idx, result in enumerate(evaluation_results):
    assert result.evaluation_ran_successfully, f"Evaluation {idx} did not run successfully: {result.evaluation_error_message}"
    assert not result.bug_resolved, f"Bug should not be resolved in evaluation {idx} with no patch."

print("Parallel evaluation with no patches completed successfully. ✅")

print("Cleaning up evaluation directory...")
assert cleanup_evaluation_dir(), "Failed to clean up evaluation directory."
print("Evaluation directory cleaned up successfully. ✅")

print("Cleaning up docker images...")
assert cleanup_sweb_docker_images(), "Failed to clean up SWE-bench Docker images."
print("Docker images cleaned up successfully. ✅")

print("SWE-bench is successfully set up and ready for evaluation. [Tests passed ✅.]")
