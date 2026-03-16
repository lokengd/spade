"""Helpers to set up and validate SWE-bench installation for evaluation."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
import json
from src.utils.logger import log
from src.core.state import EvaluationResult

from src.evaluation.constants import (
	EVAL_DIR,
	SWE_BENCH_REPO_NAME,
	SWE_BENCH_REPO_URL,
	SWE_BENCH_DEPTH_TO_CLONE,
	SWE_BENCH_BRANCH_TO_CLONE,
	VALIDATION_INSTANCE_ID,
	VALIDATION_MAX_WORKERS,
	VALIDATION_PREDICTIONS_PATH,
	VALIDATION_RUN_ID,
	DEFAULT_PREDICTIONS_PATH
)

CALLER = "Evaluator"


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[2]


def get_eval_dir_path() -> Path:
	"""Return the absolute path for the project-root EVAL_DIR."""
	return _repo_root() / EVAL_DIR


def get_logs_dir_path() -> Path:
	"""Return the absolute path for the logs directory inside EVAL_DIR."""
	return get_eval_dir_path() / "logs"


def get_instance_logs_dir(instance_id: str, run_id: str, predictions_path: str) -> Path:
	logs_dir = get_logs_dir_path()

	if predictions_path == VALIDATION_PREDICTIONS_PATH and run_id == VALIDATION_RUN_ID:
		# For validation run, logs are always stored under "gold" directory to be able to verify the results.
		return logs_dir / "run_evaluation" / VALIDATION_RUN_ID / VALIDATION_PREDICTIONS_PATH / instance_id

	instance_logs_dir = logs_dir / "run_evaluation" / run_id / DEFAULT_PREDICTIONS_PATH / instance_id
	return instance_logs_dir


def get_test_output_path(instance_id: str, run_id: str, predictions_path: str) -> Path:
	instance_logs_dir = get_instance_logs_dir(instance_id, run_id, predictions_path)
	return instance_logs_dir / "test_output.txt"


def get_report_path(instance_id: str, run_id: str, predictions_path: str) -> Path:
	instance_logs_dir = get_instance_logs_dir(instance_id, run_id, predictions_path)
	return instance_logs_dir / "report.json"


def check_docker_installed_and_running() -> bool:
	"""Return True when Docker is installed and daemon is running."""
	log("Checking if Docker is installed and running...", caller=CALLER, level=logging.INFO)

	if shutil.which("docker") is None:
		log("Docker is not installed.", caller=CALLER, level=logging.ERROR)
		return False

	try:
		result = subprocess.run(
			["docker", "info"],
			capture_output=True,
			text=True,
			check=False,
		)
	except OSError:
		log("Failed to run Docker command.", caller=CALLER, level=logging.ERROR)
		return False

	if result.returncode != 0:
		log("Docker issues, please ensure it is running.", caller=CALLER, level=logging.ERROR)
		return False

	log("Docker is installed and running.", caller=CALLER, level=logging.INFO)
	return result.returncode == 0


def clone_and_install_swe_bench() -> bool:
	"""Clone SWE-bench into EVAL_DIR and run `pip3 install -e .`.

	Returns:
		True on success, False otherwise.
	"""
	log("Cloning and installing SWE-bench...", caller=CALLER, level=logging.INFO)

	eval_dir = get_eval_dir_path()
	eval_dir.mkdir(parents=True, exist_ok=True)

	repo_dir = eval_dir / SWE_BENCH_REPO_NAME

	if not repo_dir.exists():
		clone_result = subprocess.run(
			["git", "clone", "--depth", SWE_BENCH_DEPTH_TO_CLONE, "--branch", SWE_BENCH_BRANCH_TO_CLONE, SWE_BENCH_REPO_URL],
			cwd=eval_dir,
			capture_output=True,
			text=True,
			check=False,
		)

		if clone_result.returncode != 0:
			log(f"Failed to clone SWE-bench repo. Error: {clone_result.stderr}", caller=CALLER, level=logging.ERROR)
			return False

	log("Installing SWE-bench...", caller=CALLER, level=logging.INFO)
	install_result = subprocess.run(
		["pip3", "install", "-e", "."],
		cwd=repo_dir,
		capture_output=True,
		text=True,
		check=False,
	)

	if install_result.returncode != 0:
		log(f"Failed to install SWE-bench. Error: {install_result.stderr}", caller=CALLER, level=logging.ERROR)
		return False

	log("SWE-bench cloned and installed successfully.", caller=CALLER, level=logging.INFO)

	return install_result.returncode == 0


def setup_evaluation_environment() -> bool:
	"""Set up the evaluation environment by checking Docker and installing SWE-bench."""
	log("Setting up evaluation environment...", caller=CALLER, level=logging.INFO)

	if not check_docker_installed_and_running():
		log("Docker is not installed or running. Please install and start Docker to proceed.", caller=CALLER, level=logging.ERROR)
		return False

	if not clone_and_install_swe_bench():
		log("Failed to clone and install SWE-bench. Please check the logs for details.", caller=CALLER, level=logging.ERROR)
		return False

	log("Evaluation environment set up successfully.", caller=CALLER, level=logging.INFO)

	return True


def get_report_file(report_path: Path) -> dict:
	if not report_path.exists() or not report_path.is_file():
		return {"method_success": False, "error": "Report file not found."}

	try:
		with open(report_path, "r") as f:
			report_data = json.load(f)
		return {"method_success": True, "report_data": next(iter(report_data.values()))}
	except Exception as e:
		return {"method_success": False, "error": f"Failed to read report file: {e}"}


def get_test_output_file(test_output_path: Path) -> str:
	if not test_output_path.exists() or not test_output_path.is_file():
		return {"method_success": False, "error": "Test output file not found."}

	try:
		with open(test_output_path, "r") as f:
			test_output = f.read()
		return {"method_success": True, "test_output": test_output}
	except Exception as e:
		return {"method_success": False, "error": f"Failed to read test output file: {e}"}


def is_bug_resolved(instance_id: str, run_id: str, predictions_path: str) -> dict:
	"""Read the results file generated by SWE-bench evaluation and return the test case results."""

	eval_dir = get_eval_dir_path()
	results_file = eval_dir / f"{predictions_path}.{run_id}.json"

	if not results_file.exists() or not results_file.is_file():
		return {"method_success": False, "error": "Results file not found."}

	try:
		with open(results_file, "r") as f:
			results_data = json.load(f)
		return {"method_success": True, "test_case_passed": results_data.get("completed_instances") == 1, "test_case_results": results_data}
	except Exception as e:
		return {"method_success": False, "error": f"Failed to read results file: {e}"}


def get_test_case_results(report_data: dict) -> dict:
	pass_to_pass_results = report_data.get("tests_status").get("PASS_TO_PASS")
	fail_to_pass_results = report_data.get("tests_status").get("FAIL_TO_PASS")
	total_tests = len(pass_to_pass_results.get("success", 0)) + len(pass_to_pass_results.get("failure", 0)) + len(fail_to_pass_results.get("success", 0)) + len(fail_to_pass_results.get("failure", 0))

	return {
		"bug_resolved": report_data.get("resolved"),
		"total_tests": total_tests,
		"patch_applied_successfully": report_data.get("patch_successfully_applied"),
		"pass_to_pass_success": len(pass_to_pass_results.get("failure")) == 0,
		"fail_to_pass_success": len(fail_to_pass_results.get("failure")) == 0,
		"pass_to_pass_failed_tests": pass_to_pass_results.get("failure"),
		"fail_to_pass_failed_tests": fail_to_pass_results.get("failure"),
		"pass_to_pass_successful_tests": pass_to_pass_results.get("success"),
		"fail_to_pass_successful_tests": fail_to_pass_results.get("success"),
	}


def generate_predictions_path_file(instance_id: str, patch: str, run_id: str = None) -> str:
	"""Generate a JSONL file and return unique predictions path for a given instance and run ID."""
	# {"instance_id": "sympy__sympy-20590", "model_patch": "diff --git a/.placeholder b/.placeholder\nindex e69de29..e69de29 100644\n--- a/.placeholder\n+++ b/.placeholder\n", "model_name_or_path": "test_no_predictions"}

	if run_id == VALIDATION_RUN_ID:
		# For validation run, we want to use the same predictions path and file to be able to verify the results.
		return VALIDATION_PREDICTIONS_PATH


	with open(get_eval_dir_path() / f"predictions_{instance_id}.jsonl", "w") as f:
		json_line = json.dumps({
			"instance_id": instance_id,
			"model_patch": patch,
			"model_name_or_path": DEFAULT_PREDICTIONS_PATH
		})
		f.write(json_line + "\n")

	return f"predictions_{instance_id}.jsonl"


def delete_predictions_file(predictions_file_path: str) -> None:
    """Delete the predictions file if it exists."""
    file_path = get_eval_dir_path() / predictions_file_path

    if file_path.exists() and file_path.is_file():
        file_path.unlink()
	
    return True


def _get_filtered_test_output(test_output: str) -> str:
    # Take lines including and after the line that contains "test process starts" to "tests finished"

	lines = test_output.splitlines()

	start_index = -1
	end_index = -1

	for i, line in enumerate(lines):
		if "test process starts" in line:
			start_index = i
			break
	
	for i, line in enumerate(lines):
		if "tests finished:" in line:
			end_index = i
			break
	
	if start_index != -1 and end_index != -1 and end_index > start_index:
		return "\n".join(lines[start_index:end_index+1])
	else:
		return test_output


def run_evaluation_on_instance(instance_id: str, run_id: str, patch: str, max_workers: int = 1) -> EvaluationResult:
	"""Run SWE-bench evaluation on a specific instance and verify logs."""
	log(f"Running evaluation for instance {instance_id} with run ID {run_id}... and patch {patch}", caller=CALLER, level=logging.INFO)

	eval_dir = get_eval_dir_path()

	if not (eval_dir / SWE_BENCH_REPO_NAME).exists():
		log("SWE-bench repo not found in evaluation directory.", caller=CALLER, level=logging.ERROR)
		return EvaluationResult(evaluation_ran_successfully=False, evaluation_error_message="SWE-bench repo not found in evaluation directory.")

	if not check_docker_installed_and_running():
		log("Docker is not installed or running.", caller=CALLER, level=logging.ERROR)
		return EvaluationResult(evaluation_ran_successfully=False, evaluation_error_message="Docker is not installed or running.")
	
	# Generate predictions file for the given patch and instance
	predictions_path = generate_predictions_path_file(instance_id, patch, run_id)

	cmd = [
		"python3", "-m", "swebench.harness.run_evaluation",
		"--predictions_path", predictions_path,
		"--max_workers", str(max_workers),
		"--cache_level", "instance",
		"--instance_ids", instance_id,
		"--run_id", run_id,
	]

	run_result = subprocess.run(
		cmd,
		cwd=eval_dir,
		capture_output=True,
		text=True,
		check=False,
	)

	# Clean up the predictions file after the run to avoid cluttering the evaluation directory
	delete_predictions_file(predictions_path)

	print("Evaluation command output:")
	print(run_result.stdout)
	print(run_result.stderr)

	if run_result.returncode != 0:
		log(f"Evaluation command failed with return code {run_result.returncode}.", caller=CALLER, level=logging.ERROR)
		return EvaluationResult(evaluation_ran_successfully=False, evaluation_error_message=f"Evaluation failed.\n Log:{run_result.stdout} \nError:{run_result.stderr}")

	# logs_dir = get_logs_dir_path()
	# instance_logs_dir = get_instance_logs_dir(instance_id, run_id, predictions_path)
	# results_file = eval_dir / f"{predictions_path}.{run_id}.json"

	report_file_data = get_report_file(get_report_path(instance_id, run_id, predictions_path))
	test_output_data = get_test_output_file(get_test_output_path(instance_id, run_id, predictions_path))

	if not report_file_data["method_success"]:
		log(f"Failed to get report file data: {report_file_data.get('error')}", caller=CALLER, level=logging.ERROR)
		return EvaluationResult(evaluation_ran_successfully=False, evaluation_error_message=report_file_data.get("error", "Unknown error while reading report file."))
	
	if not test_output_data["method_success"]:
		log(f"Failed to get test output file data: {test_output_data.get('error')}", caller=CALLER, level=logging.ERROR)
		return EvaluationResult(evaluation_ran_successfully=False, evaluation_error_message=test_output_data.get("error", "Unknown error while reading test output file."))

	# bug_status = is_bug_resolved(instance_id, run_id, predictions_path).get("test_case_passed", False)
	test_case_results = get_test_case_results(report_file_data["report_data"])
	test_output = _get_filtered_test_output(test_output_data["test_output"])

	log(f"Evaluation completed for instance {instance_id} with run ID {run_id}. Bug resolved: {test_case_results['bug_resolved']}.", caller=CALLER, level=logging.INFO)

	# return {"method_success": True, "logs_dir": logs_dir, "instance_logs_dir": instance_logs_dir, "results_file": results_file}
	return EvaluationResult(
		evaluation_ran_successfully=True, 
		evaluation_error_message=None, 
		bug_resolved=test_case_results["bug_resolved"], 
		patch_applied_successfully=test_case_results["patch_applied_successfully"],
		total_tests=test_case_results["total_tests"],
		pass_to_pass_success=test_case_results["pass_to_pass_success"],
		fail_to_pass_success=test_case_results["fail_to_pass_success"],
		pass_to_pass_failed_tests=test_case_results["pass_to_pass_failed_tests"],
		fail_to_pass_failed_tests=test_case_results["fail_to_pass_failed_tests"],
		pass_to_pass_successful_tests=test_case_results["pass_to_pass_successful_tests"],
		fail_to_pass_successful_tests=test_case_results["fail_to_pass_successful_tests"],
		test_output=test_output
		)


def run_evaluation_with_no_patch(instance_id: str, run_id: str, max_workers: int = 1) -> EvaluationResult:
	"""Run SWE-bench evaluation on a specific instance without applying any patches, to get the error trace."""
	log(f"Running evaluation with no patch for instance {instance_id} with run ID {run_id}...", caller=CALLER, level=logging.INFO)

	no_change_patch = "diff --git a/.placeholder b/.placeholder\nindex e69de29..e69de29 100644\n--- a/.placeholder\n+++ b/.placeholder\n"

	return run_evaluation_on_instance(instance_id=instance_id, run_id=run_id, patch=no_change_patch, max_workers=max_workers)


def test_installation() -> bool:
	"""Run SWE-bench validation command and verify expected logs are created."""
	log("Testing SWE-bench installation with validation command...", caller=CALLER, level=logging.INFO)

	evaluation_result = run_evaluation_on_instance(
		instance_id=VALIDATION_INSTANCE_ID, 
		run_id=VALIDATION_RUN_ID, 
		patch="gold", 
		max_workers=VALIDATION_MAX_WORKERS
		)
	
	eval_dir = get_eval_dir_path()

	# if not (eval_dir / SWE_BENCH_REPO_NAME).exists():
	# 	return False

	# cmd = [
	# 	"python3", "-m", "swebench.harness.run_evaluation",
	# 	"--predictions_path", VALIDATION_PREDICTIONS_PATH,
	# 	"--max_workers", VALIDATION_MAX_WORKERS,
	# 	"--instance_ids", VALIDATION_INSTANCE_ID,
	# 	"--run_id", VALIDATION_RUN_ID,
	# ]

	# run_result = subprocess.run(
	# 	cmd,
	# 	cwd=eval_dir,
	# 	capture_output=True,
	# 	text=True,
	# 	check=False,
	# )

	# print("Validation command output:")
	# print(run_result.stdout)
	# print(run_result.stderr)

	# if run_result.returncode != 0:
	# 	return False

	logs_dir = eval_dir / "logs"
	gold_logs_dir = logs_dir / "run_evaluation" / VALIDATION_RUN_ID / VALIDATION_PREDICTIONS_PATH / VALIDATION_INSTANCE_ID
	results_file = eval_dir / f"{VALIDATION_PREDICTIONS_PATH}.{VALIDATION_RUN_ID}.json"

	return logs_dir.exists() and logs_dir.is_dir() and gold_logs_dir.exists() and gold_logs_dir.is_dir() and results_file.exists() and results_file.is_file() and evaluation_result.evaluation_ran_successfully and evaluation_result.bug_resolved


def cleanup_logs_and_results_for_run(run_id: str) -> bool:
	"""Remove logs and results generated for a specific run."""
	log(f"Cleaning up logs and results for run ID {run_id}...", caller=CALLER, level=logging.INFO)

	eval_dir = get_eval_dir_path()
	logs_dir = get_logs_dir_path()
	results_file = eval_dir / f"{DEFAULT_PREDICTIONS_PATH}.{run_id}.json"

	if logs_dir.exists() and logs_dir.is_dir():
		shutil.rmtree(logs_dir)

	if results_file.exists() and results_file.is_file():
		results_file.unlink()

	log(f"Logs and results for run ID {run_id} cleaned up successfully.", caller=CALLER, level=logging.INFO)

	return True


def cleanup_sweb_docker_images() -> bool:
	"""
		Runs the command: docker images --filter=reference='swebench/sweb.eval.*' -q | xargs -r docker rmi -f
	"""

	log("Cleaning up SWE-bench Docker images...", caller=CALLER, level=logging.INFO)

	cmd = "docker images --filter=reference='swebench/sweb.eval.*' -q | xargs -r docker rmi -f"

	try:
		result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)

		if result.returncode != 0:
			log("Failed to clean up SWE-bench Docker images. Please check Docker and try again.", caller=CALLER, level=logging.ERROR)
			return False
	except OSError:
		log("Failed to run Docker command for cleaning up images.", caller=CALLER, level=logging.ERROR)
		return False

	log("SWE-bench Docker images cleaned up successfully.", caller=CALLER, level=logging.INFO)
	return True


def cleanup_validation_logs_and_results() -> bool:
    """Remove logs and results generated by the validation test."""
    log("Cleaning up validation logs and results...", caller=CALLER, level=logging.INFO)

    eval_dir = get_eval_dir_path()
    logs_dir = eval_dir / "logs"
    results_file = eval_dir / f"{VALIDATION_PREDICTIONS_PATH}.{VALIDATION_RUN_ID}.json"

    if logs_dir.exists() and logs_dir.is_dir():
        shutil.rmtree(logs_dir)

    if results_file.exists() and results_file.is_file():
        results_file.unlink()

    log("Validation logs and results cleaned up successfully.", caller=CALLER, level=logging.INFO)
    return True


def cleanup_evaluation_dir() -> bool:
    """Remove the cloned SWE-bench repo and logs."""
    log("Cleaning up evaluation directory...", caller=CALLER, level=logging.INFO)

    eval_dir = get_eval_dir_path()

    if eval_dir.exists() and eval_dir.is_dir():
        shutil.rmtree(eval_dir)

    log("Evaluation directory cleaned up successfully.", caller=CALLER, level=logging.INFO)

    return True
