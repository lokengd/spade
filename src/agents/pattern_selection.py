from src.utils.logger import log, get_loop_info
import logging
import yaml
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from src.core.state import SpadeState
from src.core.llm_client import LLM_Client
from src.core import settings
from src.utils.db_logger import db_logger
from src.utils.prompt_helper import get_failed_patches_section, get_suspicious_locations
from src.utils.snippet_extractor2 import extract_snippet


agent_name = "Pattern_Selection"

def load_prompts():
    with open(settings.PROMPTS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

class PatternSelection(BaseModel):
    pattern_id: str = Field(description="The pattern ID (e.g., P1_statement_modification)")
    scope: str = Field(description="LOCAL if fix is in local file, GLOBAL if cross-file.")
    upstream: Optional[str] = Field(description="Path to upstream file if GLOBAL, else null.")
    rationale: str = Field(description="Explanation of why this pattern fits and why the scope was chosen.")

class PatternSelectionResponse(BaseModel):
    selected_count: int = Field(description="Number of patterns selected")
    selections: List[PatternSelection] = Field(description="Top K most viable patterns and scout targets.", default_factory=list)
    overall_rationale: Optional[str] = None

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
    
    # Cap K_PATTERNS at K_PATTERNS_TOTAL
    k_val = min(settings.K_PATTERNS, settings.K_PATTERNS_TOTAL)
    log(f"{loop_info_str} Selecting Top-{k_val} Patterns...", agent_name)

    # Format the System Prompt
    system_template = prompts_config["pattern_selection"]["system"]
    system_prompt = system_template.format(
        k=k_val,
        pattern_taxonomy=taxonomy_str.strip()
    )

    # Format the User Prompt from BugContext (returned by FL Ensemble)
    bug_context = state["bug_context"]
    
    # Extract snippets for suspicious locations
    # Convert BugContext edit_locations (List) to Dict for snippet extractor
    edit_locs_dict = {}
    if bug_context.edit_locations:
        for loc in bug_context.edit_locations:
            if loc.file not in edit_locs_dict:
                edit_locs_dict[loc.file] = {"function": loc.function, "lines": loc.lines}
            else:
                # Merge lines if file already exists
                if loc.lines:
                    edit_locs_dict[loc.file]["lines"] = sorted(list(set(edit_locs_dict[loc.file].get("lines", []) + loc.lines)))

    code_snippets = extract_snippet(
        repo_path=bug_context.local_repo_path,
        suspicious_files=bug_context.suspicious_files or [],
        related_functions=bug_context.related_functions or {},
        edit_locations=edit_locs_dict,
        margin=settings.SNIPPET_CONTEXT_LINES
    )


    # Format failed patches section
    v1_patches = state.get("v1_patches", [])
    refined_patches = state.get("refined_patches", [])
    failed_patches_history = get_failed_patches_section(prompts_config, v1_patches, refined_patches, "pattern_selection")

    # Format the User Prompt
    user_template = prompts_config["pattern_selection"]["user"]
    
    # Handle optional error trace
    include_error_trace = prompts_config["pattern_selection"].get("include_error_trace", True)
    error_trace_section = ""
    if include_error_trace:
        error_trace_template = prompts_config["pattern_selection"].get("error_trace_section", "## Error Trace\n{error_trace}")
        error_trace_val = bug_context.error_trace if bug_context.error_trace else "No trace available."
        error_trace_section = error_trace_template.format(error_trace=error_trace_val)

    user_prompt = user_template.format(
        issue_text=bug_context.issue_text,
        error_trace=error_trace_section,
        suspicious_locations=get_suspicious_locations(bug_context),
        suspicious_code_snippets=code_snippets,
        failed_patches_history=failed_patches_history
    )

    # Append json_response with one shot prompt
    json_response_template = prompts_config["pattern_selection"]["json_response_zero_shot"] 
    # system_prompt += "\n" + json_response_template
    user_prompt += "\n" + json_response_template

    # Default to empty list: If anything goes wrong, K=0, meaning only the +1 Unconstrained Agent will run.
    metrics = {}
    final_selection = []
    raw_telemetry = {}
    try:
        # Get both the structured response AND telemetry metrics
        structured_response, metrics, raw_telemetry = client.generate_json_response(
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
            "resolution_status": ["pattern_selection_failed"],
            "total_metrics": metrics
        }

    return {
        "selected_patterns": final_selection,
        "inner_loop_count": 1, # Reset inner loop count at the start of a new pattern selection
        "current_patch_version": 1, # Reset patch version to 1 for the new set of patterns
        "total_metrics": metrics 
    }
