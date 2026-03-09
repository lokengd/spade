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

- 'setup_evaluation_environment()': Sets up the evaluation environment by checking for Docker, cloning the SWE-bench repository, and installing it. IMPORTANT: This function should be called before running any evaluations to ensure that the necessary dependencies and configurations are in place.

