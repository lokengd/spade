from src.utils.logger import log, get_loop_info
import uuid
import yaml
import logging
from pydantic import BaseModel, Field
from src.core.state import SpadeState, PatchCandidate, P_UNCONSTRAINED
from src.core.llm_client import LLM_Client
from src.utils.snippet_extractor import extract_snippet
from src.core import settings
from src.utils.db_logger import db_logger

agent_base_name = "PatchGen"

def load_prompts():
    with open(settings.PROMPTS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

class PatchGenerationResponse(BaseModel):
    explanation: str = Field(description="Brief explanation of the fix strategy.")
    code_diff: str = Field(description="The generated patch in UNIFIED DIFF format.")

def generate_v1_patch(state: SpadeState):
    # active_pattern is passed via Send API in graph.py
    active_pattern = state.get("active_pattern", P_UNCONSTRAINED)
    run_id = state.get("thread_id")
    
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=False)
    
    is_unconstrained = active_pattern == P_UNCONSTRAINED
    
    # Normalize pattern info for logging and prompting
    pattern_rationale = ""
    if isinstance(active_pattern, dict):
        strategy = active_pattern.get('pattern_id')
        pattern_str = f"{strategy} ({active_pattern.get('scope')})"
        pattern_rationale = active_pattern.get('rationale', "")
    else:
        pattern_str = str(active_pattern)
        strategy = str(active_pattern)

    log_prefix = "Unconstrained" if is_unconstrained else pattern_str
    # User requested format: [PatchGen] [PatternName]
    specific_agent_name = f"{agent_base_name}-{strategy}"
    log(f"{loop_info_str} {log_prefix} PatchGen working on strategy -> {pattern_str}", specific_agent_name)

    agent_config = settings.LLM_AGENTS["patchgen"]
    client = LLM_Client(agent=specific_agent_name, **agent_config)
    prompts_config = load_prompts()

    # Extract suspicious code snippets
    bug_context = state["bug_context"]
    suspicious_snippets = ""
    
    # Always include local suspicious locations
    if bug_context.edit_locations:
        for loc in bug_context.edit_locations:
            snippet = extract_snippet(
                repo_path=bug_context.local_repo_path,
                relative_file_path=loc.file,
                target_lines=loc.lines,
                function_names=loc.get_all_functions(), # combine main function and related functions for the extractor
            )
            suspicious_snippets += f"\nFile: {loc.file}\n{snippet}\n"
    elif bug_context.suspicious_files:
        for file in bug_context.suspicious_files:
            snippet = extract_snippet(
                repo_path=bug_context.local_repo_path,
                relative_file_path=file
            )
            suspicious_snippets += f"\nFile: {file}\n{snippet}\n"

    # If pattern has GLOBAL scope and an upstream file, include it too
    if isinstance(active_pattern, dict) and active_pattern.get("scope") == "GLOBAL" and active_pattern.get("upstream"):
        upstream_file = active_pattern.get("upstream")
        log(f"{loop_info_str} {log_prefix} Including upstream context: {upstream_file}", specific_agent_name)
        snippet = extract_snippet(
            repo_path=bug_context.local_repo_path,
            relative_file_path=upstream_file
        )
        suspicious_snippets += f"\nUpstream File Context: {upstream_file}\n{snippet}\n"

    if not suspicious_snippets:
        suspicious_snippets = "No code snippets available."

    # Format prompts based on unconstrained flag
    if is_unconstrained:
        system_prompt = prompts_config["patch_generation"]["unconstrained"]["system"]
        # Append json_response with one shot prompt
        system_prompt += "\n" + prompts_config["patch_generation"]["json_response_one_shot"]
        user_prompt = prompts_config["patch_generation"]["unconstrained"]["user"].format(
            issue_text=bug_context.issue_text,
            error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
            suspicious_snippets=suspicious_snippets
        )
    else:
        pattern_description = prompts_config.get("pattern_taxonomy", {}).get(strategy, "")
        system_prompt = prompts_config["patch_generation"]["pattern_guided"]["system"]
        # Append json_response with one shot prompt
        system_prompt += "\n" + prompts_config["patch_generation"]["json_response_one_shot"]
        user_prompt = prompts_config["patch_generation"]["pattern_guided"]["user"].format(
            issue_text=bug_context.issue_text,
            error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
            suspicious_snippets=suspicious_snippets,
            active_pattern=pattern_str,
            active_pattern_description=pattern_description,
            active_pattern_rationale=pattern_rationale
        )

    patch_id = f"v1_{uuid.uuid4().hex[:6]}"
    code_diff = ""
    metrics = {}
    raw_telemetry = {}

    try:
        structured_response, metrics, raw_telemetry = client.generate_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=PatchGenerationResponse,
            loop_info=loop_info_dict
        )
        code_diff = structured_response.code_diff
        explanation = structured_response.explanation

        log(f"{loop_info_str} {log_prefix} Generated v1 patch: {patch_id} using {pattern_str}", specific_agent_name, level=logging.INFO)
    except Exception as e:
        log(f"{loop_info_str} {log_prefix} Error generating v1 patch: {e}", specific_agent_name, level=logging.ERROR)
        return {
            "resolution_status": ["patchgen_failed"],
            "total_metrics": metrics
        }

    # Log Telemetry and Patch to DB
    if run_id and raw_telemetry:
        db_logger.log_telemetry(run_id, f"{agent_base_name}_{strategy}", raw_telemetry)
        db_logger.log_patch(
            patch_id=patch_id,
            run_id=run_id,
            patch_version=1,
            loop_n=state.get("outer_loop_count", 1),
            loop_m=state.get("inner_loop_count", 1),
            loop_v=1,
            pattern=strategy,
            rationale=pattern_rationale,
            explanation=explanation,
            diff=code_diff,
            tests_passed=False, #new patch gen, not yet passed
            feedback=""
        )
 
    patch = PatchCandidate(
        id=patch_id, 
        code_diff=code_diff,
        strategy=strategy,
        rationale=pattern_rationale,
        origin_v1_id=patch_id, # v1 patch is its own origin
        version=1,
        status="pending",
        execution_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
        explanation=explanation,
    )
    
    return {
        "v1_patches": [patch],
        "total_metrics": metrics
    }

def generate_refined_patch(state: SpadeState):
    ## BUG? origin_id should be renamed to winning_patch_id ? winning_patch_id maybe in v2, or v3 if v_patience is more than 2 
    origin_id = state.get("current_v1_id", "unknown_origin") 
    refined_patches = state.get("refined_patches", [])
    v1_patches = state.get("v1_patches", [])
    run_id = state.get("thread_id")
    
    # Deciding lineage: Search for the most recent refinement of this winner
    previous_patch = None
    for p in reversed(refined_patches):
        if p.origin_v1_id == origin_id:
            previous_patch = p
            break
    
    active_pattern = ""           
    pattern_rationale = ""
    if previous_patch:
        prev_version = previous_patch.version
        log(f"Start refinement chain for {origin_id} from v{prev_version}...", agent_base_name)
        previous_patch_diff = previous_patch.code_diff
        active_pattern = previous_patch.strategy
        pattern_rationale = previous_patch.rationale or ""
        v_now = prev_version + 1
    else:
        log(f"Starting refinement for {origin_id} (v2)...", agent_base_name)
        v_now = 2
        previous_patch_diff = ""
        active_pattern = P_UNCONSTRAINED # default for now, may be overwritten at code segment below        
        # Find the v1 base
        for p in v1_patches:
            if p.id == origin_id:
                previous_patch_diff = p.code_diff
                active_pattern = p.strategy
                pattern_rationale = p.rationale or ""
                break

    # Update version before getting loop info
    temp_state = state.copy()
    temp_state["current_patch_version"] = v_now
    loop_info_str, loop_info_dict = get_loop_info(temp_state, include_inner=True)
    
    specific_agent_name = f"{agent_base_name}-{active_pattern}"
    log(f"{loop_info_str} Lineage: {origin_id} -> Generating v{v_now}", specific_agent_name)

    agent_config = settings.LLM_AGENTS["patchgen"]
    client = LLM_Client(agent=specific_agent_name, **agent_config)
    prompts_config = load_prompts()

    # Format prompts
    system_prompt = prompts_config["patch_generation"]["refinement"]["system"]
    # Append json_response with one shot prompt
    system_prompt += "\n" + prompts_config["patch_generation"]["json_response_one_shot"]
    pattern_description = prompts_config.get("pattern_taxonomy", {}).get(active_pattern, "")
    user_prompt = prompts_config["patch_generation"]["refinement"]["user"].format(
        issue_text=state["bug_context"].issue_text,
        active_pattern=active_pattern or "No available.",
        active_pattern_description=pattern_description or "No available.",
        active_pattern_rationale=pattern_rationale or "No available.", 
        version=v_now - 1, 
        previous_patch_diff=previous_patch_diff,
        verdict=state.get("verdict", "No verdict available."),
        dynamic_argument=state.get("dynamic_argument", "No argument."),
        static_argument=state.get("static_argument", "No argument.")
    )

    # Maintain lineage by using the same UUID suffix as the original v1 winner
    if "_" in origin_id:
        suffix = origin_id.split("_")[-1]
    else:
        suffix = uuid.uuid4().hex[:6] # Fallback if ID format is unexpected
        
    patch_id = f"v{v_now}_{suffix}"
    code_diff = ""
    metrics = {}
    raw_telemetry = {}

    try:
        structured_response, metrics, raw_telemetry = client.generate_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=PatchGenerationResponse,
            loop_info=loop_info_dict
        )
        code_diff = structured_response.code_diff
        explanation = structured_response.explanation

        log(f"{loop_info_str} Generated refined patch: {patch_id}", specific_agent_name, level=logging.INFO)
    except Exception as e:
        log(f"{loop_info_str} Error generating refined patch: {e}", specific_agent_name, level=logging.ERROR)
        return {
            "resolution_status": ["patchgen_failed"],
            "total_metrics": metrics
        }

    # Log Telemetry and Patch to DB
    if run_id and raw_telemetry:
        db_logger.log_telemetry(run_id, f"{agent_base_name}_refined_{active_pattern}", raw_telemetry)
        db_logger.log_patch(
            patch_id=patch_id,
            run_id=run_id,
            patch_version=v_now,
            loop_n=state.get("outer_loop_count", 1),
            loop_m=state.get("inner_loop_count", 1),
            loop_v=v_now,
            pattern=active_pattern,
            rationale=pattern_rationale,
            explanation=explanation,
            diff=code_diff,
            tests_passed=False, #new patch gen, not yet passed
            feedback=state.get("verdict")
        )

    patch = PatchCandidate(
        id=patch_id, 
        code_diff=code_diff,
        strategy=active_pattern,
        rationale=pattern_rationale,
        origin_v1_id=origin_id,
        version=v_now,
        status="pending",
        explanation=explanation,
    )

    return {
        "refined_patches": [patch],
        "current_patch_version": v_now, # Sync the global state counter
        "total_metrics": metrics
    }
