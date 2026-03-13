import yaml
import pathlib

# SAPDE Orchestration
K_PATTERNS = 2           # K+1 Patterns Selection
N_OUTER_LOOPS = 1        # Outer Loop Hard Stop Limit
M_INNER_LOOPS = 1        # Inner Loop Hard Reset Limit (debate panel iterations)
V_PATIENCE = 2           # Version Patience Limit: Max versions per patch before hard reset

# Dataset and Repository Configuration
BASE_DIR = pathlib.Path(__file__).parent.parent # Project Root
DATA_DIR = BASE_DIR / "data"
DATASET_PATH = DATA_DIR / "datasets"
REPO_PATH = DATA_DIR / "repos"

# Logs Configuration
LOG_DIR = DATA_DIR / "logs"

# Ensure directories exist
DATASET_PATH.mkdir(parents=True, exist_ok=True)
REPO_PATH.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Load LLM Configuration from yaml
LLM_CONFIG_PATH = BASE_DIR / "config" / "llm.yaml"
with open(LLM_CONFIG_PATH, "r") as f:
    _llm_data = yaml.safe_load(f)

# Expose the configuration dictionaries globally
LLM_AGENTS = _llm_data.get("agents", {})
COST_TABLE = _llm_data.get("costs", {})