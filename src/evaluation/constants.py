"""Centralized constants for evaluation workflows."""

EVAL_DIR = "EVAL_DIR"
SWE_BENCH_REPO_URL = "https://github.com/SWE-bench/SWE-bench.git"
SWE_BENCH_REPO_NAME = "SWE-bench"
SWE_BENCH_DEPTH_TO_CLONE = "1"
SWE_BENCH_BRANCH_TO_CLONE = "main"

VALIDATION_PREDICTIONS_PATH = "gold"
VALIDATION_MAX_WORKERS = "1"
VALIDATION_INSTANCE_ID = "sympy__sympy-20590"
VALIDATION_RUN_ID = "validate-gold"

DEFAULT_PREDICTIONS_PATH = "spade"

NO_CHANGE_PATCH = "diff --git a/.placeholder b/.placeholder\nindex e69de29..e69de29 100644\n--- a/.placeholder\n+++ b/.placeholder\n"
