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
results = get_test_case_results(instance_id=VALIDATION_INSTANCE_ID, run_id=VALIDATION_RUN_ID, predictions_path=VALIDATION_PREDICTIONS_PATH)
assert results["method_success"], f"Failed to get test case results: {results.get('error')}"
assert results.get("test_case_passed"), "Validation test case did not pass."
print("Validation test case passed successfully. ✅")

print("Cleaning up validation logs and results...")
assert cleanup_validation_logs_and_results(), "Failed to clean up logs and results after testing."
print("Logs and results cleaned up successfully. ✅")

print("Cleaning up evaluation directory...")
assert cleanup_evaluation_dir(), "Failed to clean up evaluation directory."
print("Evaluation directory cleaned up successfully. ✅")

# To test "run_evaluation_on_instance"

print("SWE-bench is successfully set up and ready for evaluation. [Tests passed.]")
