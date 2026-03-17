import yaml
import pathlib
import sys

# Load Experiments Configuration from yaml
BASE_DIR = pathlib.Path(__file__).parent.parent.parent # Project Root
EXPERIMENTS_CONFIG_PATH = BASE_DIR / "config" / "experiments.yaml"

with open(EXPERIMENTS_CONFIG_PATH, "r") as f:
    EXPERIMENTS_DATA = yaml.safe_load(f)

ACTIVE_EXPERIMENTS = EXPERIMENTS_DATA.get("active_experiments", [])
EXPERIMENTS = EXPERIMENTS_DATA.get("experiments", {})

# Global orchestration constants (placeholders)
K_PATTERNS = 2
N_OUTER_LOOPS = 2
M_INNER_LOOPS = 1
V_PATIENCE = 2
SNIPPET_CONTEXT_LINES = 15
FL_RESULTSET = ""

# Default Configuration Paths
DEFAULT_LLM_CONFIG_PATH = BASE_DIR / "config" / "llm.yaml"
DEFAULT_PROMPTS_CONFIG_PATH = BASE_DIR / "config" / "prompts.yaml"

# Active Configuration Paths (can be overridden by experiments)
LLM_CONFIG_PATH = DEFAULT_LLM_CONFIG_PATH
PROMPTS_CONFIG_PATH = DEFAULT_PROMPTS_CONFIG_PATH

# Expose the configuration dictionaries globally
LLM_AGENTS = {}
COST_TABLE = {}

def load_llm_config(config_path: pathlib.Path):
    """Loads LLM configuration from a yaml file."""
    global LLM_AGENTS, COST_TABLE
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    LLM_AGENTS = data.get("agents", {})
    COST_TABLE = data.get("costs", {})

def update_orchestration_settings(experiment_id: str):
    """Updates global orchestration constants and config paths based on the experiment_id."""
    global K_PATTERNS, N_OUTER_LOOPS, M_INNER_LOOPS, V_PATIENCE, SNIPPET_CONTEXT_LINES, FL_RESULTSET
    global LLM_CONFIG_PATH, PROMPTS_CONFIG_PATH

    exp = EXPERIMENTS.get(experiment_id)
    if not exp:
        print(f"FATAL ERROR: Experiment '{experiment_id}' not found in experiments.yaml.")
        sys.exit(1)

    required_params = ["k_patterns", "n_outer_loops", "m_inner_loops", "v_patience", "bug_list", "snippet_context_lines", "fl_resultset"]
    for param in required_params:
        if param not in exp:
            print(f"FATAL ERROR: Missing parameter '{param}' in experiment '{experiment_id}'.")
            sys.exit(1)

    K_PATTERNS = exp["k_patterns"]
    N_OUTER_LOOPS = exp["n_outer_loops"]
    M_INNER_LOOPS = exp["m_inner_loops"]
    V_PATIENCE = exp["v_patience"]
    SNIPPET_CONTEXT_LINES = exp["snippet_context_lines"]
    FL_RESULTSET = exp["fl_resultset"]

    # Handle LLM and Prompts config overrides
    llm_cfg = exp.get("llm_config")
    if llm_cfg:
        LLM_CONFIG_PATH = BASE_DIR / llm_cfg
    else:
        LLM_CONFIG_PATH = DEFAULT_LLM_CONFIG_PATH

    prompts_cfg = exp.get("prompts_config")
    if prompts_cfg:
        PROMPTS_CONFIG_PATH = BASE_DIR / prompts_cfg
    else:
        PROMPTS_CONFIG_PATH = DEFAULT_PROMPTS_CONFIG_PATH

    # Reload LLM config
    load_llm_config(LLM_CONFIG_PATH)

    return exp

# Initialize with the first active experiment if available, otherwise load defaults
if ACTIVE_EXPERIMENTS:
    update_orchestration_settings(ACTIVE_EXPERIMENTS[0])
else:
    load_llm_config(DEFAULT_LLM_CONFIG_PATH)

# Dataset and Repository Configuration
DATA_DIR = BASE_DIR / "data"
DATASET_PATH = DATA_DIR / "datasets"
REPO_PATH = DATA_DIR / "repos"

# Logs Configuration
LOG_DIR = DATA_DIR / "logs"

# Ensure directories exist
DATASET_PATH.mkdir(parents=True, exist_ok=True)
REPO_PATH.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
