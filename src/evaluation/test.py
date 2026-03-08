"""Test script to validate the setup and functionality of SWE-bench for evaluation purposes."""

from swe_bench_lite_utils import *

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

print("Cleaning up logs and results...")
assert cleanup_logs_and_results(), "Failed to clean up logs and results after testing."
print("Logs and results cleaned up successfully. ✅")

print("Cleaning up evaluation directory...")
assert cleanup_evaluation_dir(), "Failed to clean up evaluation directory."
print("Evaluation directory cleaned up successfully. ✅")

print("SWE-bench is successfully set up and ready for evaluation. [Tests passed.]")
