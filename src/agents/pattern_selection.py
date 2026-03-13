from src.utils.logger import log
import logging
import yaml
from pydantic import BaseModel, Field
from typing import List
from src.core.state import SpadeState, get_loop_info
from src.core.llm_client import LLM_Client
from config.settings import K_PATTERNS, LLM_AGENTS

agent_name = "Pattern_Selection"

def load_prompts():
    with open("config/prompts.yaml", "r") as f:
        return yaml.safe_load(f)

class PatternSelectionResponse(BaseModel):
    selected_patterns: List[str] = Field(description="List of selected semantic fix patterns")

def run(state: SpadeState):

    # Initialize 
    agent_config = LLM_AGENTS["pattern_selection"]
    client = LLM_Client(agent=agent_name, **agent_config)

    loop_info = get_loop_info(state, include_inner=False)
    log(f"{loop_info} Selecting Top-{K_PATTERNS} Patterns...", agent_name)

    # Load configuration and patterns
    prompts_config = load_prompts()
    fix_patterns = prompts_config["fix_patterns"]
    
    # Format the System Prompt
    system_template = prompts_config["pattern_selection"]["system"]
    system_prompt = system_template.format(
        k=K_PATTERNS,
        patterns=", ".join(fix_patterns)
    )

    # Format the User Prompt from BugContext
    bug_context = state["bug_context"]
    user_template = prompts_config["pattern_selection"]["user"]
    user_prompt = user_template.format(
        issue_text=bug_context.issue_text,
        suspicious_files=", ".join(bug_context.suspicious_files),
        error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available"
    )

    metrics = {}
    try:
        # Get both the structured response AND telemetry metrics
        structured_response, metrics = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=PatternSelectionResponse
        )
        final_selection = structured_response.selected_patterns[:K_PATTERNS]
        
    except Exception as e:
        log(f"Failed to select patterns via LLM: {e}. Falling back to defaults.", agent_name, level=logging.ERROR)
        # Fallback to the first K patterns to prevent graph crash
        final_selection = fix_patterns[:K_PATTERNS]

    return {
        "selected_patterns": final_selection,
        "inner_loop_count": 1, # Reset inner loop count at the start of a new pattern selection,  safe for the first run or hard reset
        "current_patch_version": 1, # Reset patch version to 1 for the new set of patterns
        "total_metrics": metrics 
    }
    