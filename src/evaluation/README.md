# Evaluation Module

This module provides utilities for setting up and running evaluations using the SWE-bench Lite framework. It includes functions to check for Docker installation, clone and install the SWE-bench repository, run evaluations, and clean up evaluation logs and results.

## Test Installation

To validate the setup and functionality of SWE-bench for evaluation purposes, you can run the `test_evaluation_package.py` script. This script will check if Docker is installed and running, clone the SWE-bench repository, install it, and run a sample evaluation to ensure everything is working correctly. Run the following command in your terminal from the root directory of the project:

```bash
python3 -m src.evaluation.test_evaluation_package
```

The final output should indicate that the SWE-bench setup validation was successful, confirming that the evaluation environment is ready for use.

```
SWE-bench is successfully set up and ready for evaluation. [Tests passed ✅.]
```

## API Reference

- `setup_evaluation_environment()`: Sets up the evaluation environment by checking for Docker, cloning the SWE-bench repository, and installing it. IMPORTANT: This function should be called before running any evaluations to ensure that the necessary dependencies and configurations are in place.
- `test_installation()`: Validates the installation of SWE-bench by running a sample evaluation and checking for the expected results
- `run_evaluation_on_instance()`: Runs SWE-bench evaluation on a specific instance and passed patch and returns the evaluation result. See `EvaluationResult` for details on the structure of the returned result in `src/core/state.py`. Parameters include the instance ID, run ID, and patch for the evaluation.
- `run_evaluation_with_no_patch()`: Runs SWE-bench evaluation on a specific instance without a patch and returns the evaluation result. To be used for obtaining failing test case information and error traces for the default version of the code before applying any patches. Parameters include the instance ID, and run ID.
- `cleanup_logs_and_results_for_run()`: Cleans up the logs and results for a run. Parameters include the run ID. This function is useful for cleaning up after an evaluation run, especially if you want to re-run the evaluation with different patches or configurations without interference from previous logs and results.
- `cleanup_evaluation_dir()`: Cleans up the evaluation directory. You will have to run `setup_evaluation_environment()` again to set up the evaluation environment after running this function.
- 'cleanup_sweb_docker_images()': Cleans up the SWE-bench Docker images from your system. This can be useful if you want to free up disk space or if you want to ensure a clean slate for future evaluations. Recommended to run this function after a task instance has processed and is no longer needed, and moving to the next task instance to evaluate.
