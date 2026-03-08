"""Test script to validate the setup and functionality of SWE-bench for evaluation purposes."""

from swe_bench_lite_utils import *

assert check_docker_installed_and_running(), "Docker is not installed or running. Please install and start Docker to proceed."
assert clone_and_install_swe_bench(), "Failed to clone and install SWE-bench."
assert test_installation(), "SWE-bench installation test failed."
assert cleanup_logs_and_results(), "Failed to clean up logs and results after testing."
assert cleanup_evaluation_dir(), "Failed to clean up evaluation directory."

print("SWE-bench is successfully set up and ready for evaluation. [Tests passed.]")
