from src.utils.logger import log, get_loop_info
import logging
import yaml
from pydantic import BaseModel, Field
from typing import List, Optional
from src.core.state import SpadeState
from src.core.llm_client import LLM_Client
from src.core import settings
from src.utils.db_logger import db_logger

agent_name = "Pattern_Selection"

def load_prompts():
    with open(settings.PROMPTS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

class PatternScoutSelection(BaseModel):
    pattern_id: str = Field(description="The pattern ID (e.g., P1_statement_modification)")
    scope: str = Field(description="LOCAL if fix is in local file, GLOBAL if cross-file.")
    upstream: Optional[str] = Field(description="Path to upstream file if GLOBAL, else null.")
    rationale: str = Field(description="Explanation of why this pattern fits and why the scope was chosen.")

class PatternSelectionResponse(BaseModel):
    selected_count: int = Field(description="Number of patterns selected")
    selections: List[PatternScoutSelection] = Field(description="Top K most viable patterns and scout targets.", default_factory=list)


def run(state: SpadeState):

    # Initialize 
    agent_config = settings.LLM_AGENTS["pattern_selection"]
    client = LLM_Client(agent=agent_name, **agent_config)
    run_id = state.get("thread_id")

    # Load configuration and patterns
    prompts_config = load_prompts()
    taxonomy_dict = prompts_config.get("pattern_taxonomy", {})
    taxonomy_str = ""
    for pat_id, description in taxonomy_dict.items():
        # format the taxonomy into a readable list for the system prompt
        taxonomy_str += f"- {pat_id}: {description.strip()}\n\n"

    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=False)
    log(f"{loop_info_str} Selecting Top-{settings.K_PATTERNS} Patterns...", agent_name)

    # Format the System Prompt
    system_template = prompts_config["pattern_selection"]["system"]
    system_prompt = system_template.format(
        k=settings.K_PATTERNS,
        pattern_taxonomy=taxonomy_str.strip()
    )

    # Format the User Prompt from BugContext (returned by FL Ensemble)
    bug_context = state["bug_context"]
    locations_str = ""
    if bug_context.edit_locations:
        locations_str += "--- Edit Locations ---\n"
        for loc in bug_context.edit_locations:
            func_str = f" | Func: {loc.function}" if loc.function else ""
            lines_str = f" | Lines: {loc.lines}" if loc.lines else ""
            locations_str += f"- File: {loc.file}{func_str}{lines_str}\n"
            # Inject code snippet if available
            if loc.snippet:
                locations_str += f"{loc.snippet}\n\n"
    
    if bug_context.related_functions:
        locations_str += "--- Related Functions ---\n"
        for file, funcs in bug_context.related_functions.items():
            locations_str += f"- {file}: {', '.join(funcs)}\n"
        locations_str += "\n"
            
    if not bug_context.edit_locations and bug_context.suspicious_files:
        locations_str += "--- Suspicious Files ---\n"
        locations_str += "\n".join([f"- {f}" for f in bug_context.suspicious_files])
        locations_str += "\n"
        
    if not locations_str.strip():
        locations_str = "No specific locations identified by Fault Localization."


    # Format the User Prompt
    user_template = prompts_config["pattern_selection"]["user"]
    user_prompt = user_template.format(
        issue_text=bug_context.issue_text,
        error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
        suspicious_locations=locations_str.strip()
    )

    # Default to empty list: If anything goes wrong, K=0, meaning only the +1 Unconstrained Agent will run.
    metrics = {}
    final_selection = []
    raw_telemetry = {}
    try:
        # Get both the structured response AND telemetry metrics
        structured_response, metrics, raw_telemetry = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=PatternSelectionResponse,
            loop_info=loop_info_dict
        )
        
        # Log to DB
        if run_id and raw_telemetry:
            db_logger.log_telemetry(run_id, agent_name, raw_telemetry)

        if structured_response.selected_count == 0 or not structured_response.selections:
            log("No patterns matched. Proceeding with K=0.", agent_name, level=logging.INFO)
        else:
            # Enforce the K_PATTERNS limit and convert Pydantic models to dicts for LangGraph
            final_selection = [s.model_dump() for s in structured_response.selections[:settings.K_PATTERNS]]
            selected_ids = [s["pattern_id"] for s in final_selection]
            log(f"Selected {len(final_selection)} patterns: {selected_ids}", agent_name, level=logging.INFO)

    except Exception as e:
        log(f"Pattern Selection captured an exception: {e}.", agent_name, level=logging.ERROR)
        return {
            "resolution_status": "pattern_selection_failed",
            "total_metrics": metrics
        }

    return {
        "selected_patterns": final_selection,
        "inner_loop_count": 1, # Reset inner loop count at the start of a new pattern selection
        "current_patch_version": 1, # Reset patch version to 1 for the new set of patterns
        "total_metrics": metrics 
    }
