"""Test script to validate the setup and functionality of SWE-bench for evaluation purposes."""

from src.evaluation.swe_bench_lite_utils import *

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

test_case_results = get_test_case_results(report_data["report_data"])
assert test_case_results['bug_resolved'], "Bug was not resolved according to test case results."
assert test_case_results['pass_to_pass_success'], "PASS_TO_PASS test case did not pass."
assert test_case_results['fail_to_pass_success'], "FAIL_TO_PASS test case did not pass."
print("Validation test case passed successfully. ✅")

print("Cleaning up validation logs and results...")
assert cleanup_validation_logs_and_results(), "Failed to clean up logs and results after testing."
print("Logs and results cleaned up successfully. ✅")

print("Cleaning up evaluation directory...")
assert cleanup_evaluation_dir(), "Failed to clean up evaluation directory."
print("Evaluation directory cleaned up successfully. ✅")

# To test "run_evaluation_on_instance"

print("SWE-bench is successfully set up and ready for evaluation. [Tests passed ✅.]")
