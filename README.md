# ♠️ SPADE: Semantic Pattern-Guided LLM-Based Multi-Agent DebatE for Automated Program Repair

[![Paper](https://img.shields.io/badge/ArXiv-Pending-red.svg)](#) [![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![LangGraph](https://img.shields.io/badge/LangGraph-Enabled-orange.svg)](https://github.com/langchain-ai/langgraph) 

SPADE is an LLM-based multi-agent framework designed for Automated Program Repair (APR). 

---

## 1. Setup & Installation

Follow these steps to initialize the SPADE environment and dependencies.

### 1.1. Environment Setup
Clone the repository and run the setup script to initialize the virtual environment and install dependencies.
```bash
# Make the script executable 
chmod +x setup.sh

# Run the setup script
./setup.sh
```

### 1.2. LLM Setup

By default, SPADE runs locally and free using `qwen2.5-coder:latest`.

* Download and install Ollama from [ollama.com](https://ollama.com/).
* Download the model:
```bash
ollama pull qwen2.5-coder:latest
```
* Start the Server: Ensure the Ollama application is running in the background. The server runs locally on http://localhost:11434.


### 1.3. Run the Evaluation
```bash
# Activate the virtual environment
source .venv/bin/activate

# Start the evaluation
python3 main.py
```

## 2. LLM Configuration

By default, SPADE uses `qwen2.5-coder:latest` for all agents.

### 2.1. Overriding Defaults

You can override LLM models, adjust temperatures, and configure endpoints for specific agents by editing the `config/llm.yaml` file. For example:
```yaml
agents:
  pattern_selection:
    provider: "gemini"
    model: "gemini-2.5-flash"
    temperature: 0.0
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
    api_key_env: "GEMINI_API_KEY"
  judge:
    provider: "openai"
    model: "gpt-4o"
    temperature: 0.0
    base_url: null
    api_key_env: "OPENAI_API_KEY"
```

For cloud providers (OpenAI, Gemini), set the corresponding environment variables:
```bash
export OPENAI_API_KEY="[your-openai-api-key]"
export GEMINI_API_KEY="[your-gemini-api-key]"
```

### 2.2. Tracking cost 

SPADE includes built-in cost tracking to automatically calculate total cost based on token usage, configurable in `config/llm.yaml`.
```yaml
# Cost per 1,000,000 (1 Million) tokens in USD
costs:
  qwen2.5-coder:latest:
    input: 0.0
    output: 0.0
  gpt-4o:
    input: 2.50
    output: 10.00
  gemini-2.5-flash:
    input: 0.075
    output: 0.30
```

## 3. Solution Design

SPADE is orchestrated as a multi-agent graph using LangGraph, designed for iterative and collaborative program repair.

### 3.1. Orchestration Flow

![SPADE Architecture](spade_graph.png)

The orchestration consists of several key stages:
1. **Fault Localization & Reproduction**: The `fl_ensemble` and `reproduction` agents identify the bug location and generate a reproduction script.
2. **Pattern Selection**: The `pattern_selection` agent selects **K** semantic patterns most relevant to the bug.
3. **Parallel Patch Generation**: **K+1** parallel `patchgen` agents generate patch candidates (K based on patterns + 1 unconstrained).
4. **Debate Panel**: A `dynamic_debater` (pro-patch from runtime analysis) and `static_debater` (pro-patch from structural analysis) exchange arguments and rebuttals.
5. **Verdict & Refinement**: A `judge` agent selects the winner of the patch candidate closest to the real patch or provides feedback for refinement over **M** inner loops of debates.

### 3.2. Key Parameters of Experiments

Experiments are configured in `config/experiments.yaml` using the following parameters:

| Parameter | Description |
| :--- | :--- |
| **K** (`k_patterns`) | Number of semantic patterns selected for parallel patch generation. |
| **N** (`n_outer_loops`) | Maximum number of full orchestration attempts (re-selecting patterns/trying new approaches) per bug. |
| **M** (`m_inner_loops`) | Maximum number of debate and refinement cycles for a selected patch candidate. |
| **V** (`v_patience`) | Maximum number of refinement attempts (via version increments) before giving up on a specific patch candidate within the debate panel. |
| **llm_config** | *(Optional)* Override the default `llm.yaml` with a customized LLM configuration. |
| **prompts_config** | *(Optional)* Override the default `prompts.yaml` with customized agent prompts. |

By customizing `llm_config` and `prompts_config`, you can easily test different model providers or prompt engineering strategies for specific ablation studies or model-specific optimizations.

### 3.3. Ablation Studies

SPADE supports various ablation configurations to evaluate the impact of specific components. For example:
* **K=0**: Skips pattern selection, proceeding directly to unconstrained patch generation.
* **M=0**: Skips the debate panel and iterative refinement, relying on initial patch candidates.

### 3.4. Dataset

By default, SPADE is evaluated on **[SWE-bench-Lite](https://www.swebench.com/lite.html)**, a benchmark consisting of 300 real-world software engineering issues from popular open-source repositories.

## 4. Monitoring & Troubleshooting

### 4.1. Viewing Execution Traces
Detailed, timestamped execution logs, including token consumption and reasoning traces, are automatically saved to the `data/logs/` directory for every run. These logs provide a granular view of agent interactions and decision-making processes.

### 4.2. Collecting Metrics
SPADE persists experiment data to a local SQLite database (`data/spade_results.db`) which allows for post-run analysis and performance tracking. The following metrics are automatically collected and aggregated:

*   **Resolution Metrics**: Total bugs processed, resolution rate (%), and Fault Localization (FL) accuracy.
*   **Repair Efficiency**: 
    *   `pass@1`: Success on the first attempt (N=1, M=1, V=1).
    *   `debate_rescues@1`: Success on the the first debate loop (N=1, M=1, V=2).
    *   `inner_loop_rescues`: Success achieved in subsequent debate cycles (M > 1).
    *   `outer_loop_rescues`: Success after re-triggering pattern selection (N > 1).
*   **LLM Telemetry**: Token usage (input/output), cost per agent, model performance, and execution duration per agent.
*   **Patch Evaluations**: A history of all generated patches, their diffs, applied patterns, and test results (plausibility).

You can query the database directly to extract custom insights or generate summary reports.

### 4.3. Resetting Agent Memory
SPADE uses a local SQLite checkpointer to persist agent state and memory across runs. To completely clear the memory and start fresh (e.g., to re-run a bug from scratch):

```bash
# Delete the local checkpointer database to clear agent memory
rm data/checkpoints.sqlite*
```

## 5. Acknowledgement

- [SWE-bench-Lite](https://www.swebench.com/lite.html)
- [LangGraph](https://github.com/langchain-ai/langgraph)
