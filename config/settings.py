import os
import pathlib

# SAPDE Orchestration
K_PATTERNS = 2           # K+1 Patterns Selection
N_OUTER_LOOPS = 3        # Outer Loop Hard Stop Limit
M_INNER_LOOPS = 1        # Inner Loop Hard Reset Limit (debate panel iterations)
V_PATIENCE = 2           # Version Patience Limit: Max versions per patch before hard reset

# LLM Configuration
LLM_PROVIDER = "ollama"  # Options: "openai", "gemini", "ollama", "local"
LLM_MODEL_NAME = "qwen2.5vl:3b"
LLM_TEMPERATURE_STABLE = 0.0  # For structured output/selection
LLM_TEMPERATURE_CREATIVE = 0.7  # For debates and rebuttals

# API Keys (Loaded from environment variables)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Local Endpoints
OLLAMA_BASE_URL = "http://localhost:11434/v1"

# Dataset and Repository Configuration
BASE_DIR = pathlib.Path(__file__).parent.parent # Project Root
DATA_DIR = BASE_DIR / "data"
DATASET_PATH = DATA_DIR / "datasets"
REPO_PATH = DATA_DIR / "repos"

# Ensure directories exist
DATASET_PATH.mkdir(parents=True, exist_ok=True)
REPO_PATH.mkdir(parents=True, exist_ok=True)