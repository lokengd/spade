import requests

from src.utils.logger import log, get_loop_info
import uuid
import yaml
import logging
from pydantic import BaseModel, Field
from src.core.state import SpadeState, PatchCandidate, P_UNCONSTRAINED
from src.core.llm_client import LLM_Client, OpenRouterClient
from src.utils.snippet_extractor import extract_snippet, extract_snippet_fix
from src.core import settings
from src.utils.db_logger import db_logger
from src.utils.prompt_helper import get_failed_patches_section

agent_base_name = "PatchGen"

TEMPERATURE_RANGE = [0.1, 0.8]
LLM_SETTINGS = {
    "model": "gpt-oss-120b:nitro", #"qwen3.5:9b", # qwen2.5-coder:14b # deepseek-r1:latest gpt-oss:20b gpt-oss-120b
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 20,
    "min_p": 0.0,
    "presence_penalty": 1.5,
    "repetition_penalty": 2.0,
}

NUM_SAMPLES = 1

PROMPT = """
            You are an expert code-repair agent. Your task is to fix a bug in a specific file using a provided Fix-Pattern.

            ### 1. INPUT DATA
            - **File Path**: {filepath}
            - **Fix-Pattern**: {pattern}

            --- BEGIN ISSUE ---
            {problem_statement}
            --- END ISSUE ---

            --- SOURCE CODE ---
            {file_context}
            --- END SOURCE CODE ---

            ### 2. INSTRUCTIONS
            Follow these steps in order:

            1. **REASONING**: Briefly explain where in the code corrections are needed based on the Fix-Pattern. 
            2. **OUTPUT PATCH**: Generate the SEARCH/REPLACE block. 

            ### 3. CRITICAL RULES
            - The SEARCH block must match the Source Code EXACTLY (same indentation, same spaces).
            - Include 3 to 5 lines of surrounding context in the SEARCH block to make it unique.
            - If no bugs are found, respond exactly with: `# No changes needed`

            ### 4. OUTPUT FORMAT

            ```python
            ### {filepath}
            <<<<<<< SEARCH
            [exact code from source]
            =======
            [your fixed code]
            >>>>>>> REPLACE
        """



def load_prompts():
    with open(settings.PROMPTS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

class PatchGenerationResponse(BaseModel):
    explanation: str = Field(description="Brief explanation of the fix pattern.")
    code_diff: str = Field(description="The generated patch in UNIFIED DIFF format.")


def generate_v1_patch_bk(state: SpadeState):
    # active_pattern is passed via Send API in graph.py
    active_pattern = state.get("active_pattern", P_UNCONSTRAINED)
    run_id = state.get("thread_id")
    
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=False)
    
    is_unconstrained = active_pattern == P_UNCONSTRAINED
    
    # Normalize pattern info for logging and prompting
    pattern_rationale = ""
    if isinstance(active_pattern, dict):
        pattern = active_pattern.get('pattern_id')
        pattern_str = f"{pattern} ({active_pattern.get('scope')})"
        pattern_rationale = active_pattern.get('rationale', "")
    else:
        pattern_str = str(active_pattern)
        pattern = str(active_pattern)

    log_prefix = "Unconstrained" if is_unconstrained else pattern_str
    # User requested format: [PatchGen] [PatternName]
    specific_agent_name = f"{agent_base_name}-{pattern}"
    log(f"{loop_info_str} {log_prefix} PatchGen working on pattern -> {pattern_str}", specific_agent_name)

    agent_config = settings.LLM_AGENTS["patchgen"]
    # client = LLM_Client(agent=specific_agent_name, **agent_config)
    client = OpenRouterClient(api_key=API_KEY, model=LLM_SETTINGS["model"])
    prompts_config = load_prompts()

    # Extract suspicious code snippets
    bug_context = state["bug_context"]
    suspicious_snippets = ""
    
    # # Always include local suspicious locations
    # if bug_context.edit_locations:
    #     for loc in bug_context.edit_locations:
    #         snippet = extract_snippet(
    #             repo_path=bug_context.local_repo_path,
    #             relative_file_path=loc.file,
    #             target_lines=loc.lines,
    #             function_names=loc.get_all_functions(), # combine main function and related functions for the extractor
    #         )
    #         suspicious_snippets += f"\nFile: {loc.file}\n{snippet}\n"
    # elif bug_context.suspicious_files:
    #     for file in bug_context.suspicious_files:
    #         snippet = extract_snippet(
    #             repo_path=bug_context.local_repo_path,
    #             relative_file_path=file
    #         )
    #         suspicious_snippets += f"\nFile: {file}\n{snippet}\n"

    for file in bug_context.suspicious_files:
        snippet = bug_context.file_snippets.get(file)
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

    # Format failed patches section
    v1_patches = state.get("v1_patches", [])
    refined_patches = state.get("refined_patches", [])
    failed_patches_history = get_failed_patches_section(prompts_config, v1_patches, refined_patches, "patch_generation", pattern_filter=pattern)
    # debate_history = state.get("debate_history", []) #for when we want to include debate history later
    # debate_history_section = get_debate_history_section(prompts_config, debate_history, "patch_generation")

    
    # Format prompts based on unconstrained flag
    if is_unconstrained:
        system_prompt = prompts_config["patch_generation"]["unconstrained"]["system"]
        # Append json_response with one shot prompt
        system_prompt += "\n" + prompts_config["patch_generation"]["json_response_one_shot"]
        user_prompt = prompts_config["patch_generation"]["unconstrained"]["user"].format(
            issue_text=bug_context.issue_text,
            error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
            suspicious_snippets=suspicious_snippets,
            failed_patches_history=failed_patches_history
        )
    else:
        pattern_description = prompts_config.get("pattern_taxonomy", {}).get(pattern, "")
        system_prompt = prompts_config["patch_generation"]["pattern_guided"]["system"]
        # Append json_response with one shot prompt
        system_prompt += "\n" + prompts_config["patch_generation"]["json_response_one_shot"]
        user_prompt = prompts_config["patch_generation"]["pattern_guided"]["user"].format(
            issue_text=bug_context.issue_text,
            error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
            suspicious_snippets=suspicious_snippets,
            active_pattern=pattern_str,
            active_pattern_description=pattern_description,
            active_pattern_rationale=pattern_rationale,
            failed_patches_history=failed_patches_history
        )

    patch_id = f"v1_{uuid.uuid4().hex[:6]}"
    code_diff = ""
    metrics = {}
    raw_telemetry = {}

    try:
        structured_response, metrics, raw_telemetry = client.generate_json_response(# generate_text
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=PatchGenerationResponse,
            loop_info=loop_info_dict
        )
        # print(">> Structured Response:")
        # print(structured_response)
        # exit(1)
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
        db_logger.log_telemetry(run_id, f"{agent_base_name}_{pattern}", raw_telemetry)
        db_logger.log_patch(
            patch_id=patch_id,
            run_id=run_id,
            patch_version=1,
            loop_n=state.get("outer_loop_count", 1),
            loop_m=state.get("inner_loop_count", 1),
            loop_v=1,
            pattern=pattern,
            rationale=pattern_rationale,
            explanation=explanation,
            diff=code_diff,
            tests_passed=False, #new patch gen, not yet passed
            feedback=""
        )
 
    patch = PatchCandidate(
        id=patch_id, 
        code_diff=code_diff,
        pattern=pattern,
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
        active_pattern = previous_patch.pattern
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
                active_pattern = p.pattern
                pattern_rationale = p.rationale or ""
                break

    # Update version before getting loop info
    temp_state = state.copy()
    temp_state["current_patch_version"] = v_now
    loop_info_str, loop_info_dict = get_loop_info(temp_state, include_inner=True)
    
    specific_agent_name = f"{agent_base_name}-{active_pattern}"
    log(f"{loop_info_str} Lineage: {origin_id} -> Generating v{v_now}", specific_agent_name)

    agent_config = settings.LLM_AGENTS["patchgen"]
    # client = LLM_Client(agent=specific_agent_name, **agent_config)
    client = OpenRouterClient(api_key=API_KEY, model=LLM_SETTINGS["model"])
    prompts_config = load_prompts()

    # Format failed patches section
    failed_patches_history = get_failed_patches_section(prompts_config, v1_patches, refined_patches, "patch_generation", pattern_filter=active_pattern)

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
        static_argument=state.get("static_argument", "No argument."),
        failed_patches_history=failed_patches_history
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
        pattern=active_pattern,
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









# ---------------------

import argparse
from email.mime import text
import json
import os
import shutil
import subprocess
import hashlib
import requests
from difflib import unified_diff
from pathlib import Path
from datetime import datetime

from datasets import load_dataset

import re
from typing import Dict, List, Tuple, Optional, Set
import random


# ============== Configuration ==============
API_KEY = "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"
TEMPERATURE_RANGE = [0.1, 0.8]
LLM_SETTINGS = {
    "model": "gpt-oss-120b:nitro", #"qwen3.5:9b", # qwen2.5-coder:14b # deepseek-r1:latest gpt-oss:20b gpt-oss-120b
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 20,
    "min_p": 0.0,
    "presence_penalty": 1.8,
    "repetition_penalty": 2.5,
}

# ============== Code Processing ==============

def extract_python_blocks(text: str) -> list[str]:
    if not isinstance(text, str):
        raise TypeError(f"Expected a string, got {type(text).__name__}")

    fence_re = re.compile(
        r"""
        ^\s*```python[ \t]*\n      # opening fence (with optional spaces)
        (.*?)                     # block content (non‑greedy)
        ^\s*```[ \t]*\n?          # closing fence (optional trailing newline)
        """,
        flags=re.MULTILINE | re.DOTALL | re.VERBOSE,
    )

    return [block.rstrip("\n") for block in fence_re.findall(text)]


def parse_search_replace(block: str, file_contents: dict, verbose: bool = True) -> tuple[list, list]:
    """Parse SEARCH/REPLACE blocks and apply edits."""
    edited_files, new_contents = [], []
    current_file = None
    edits = {}
    
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("### "):
            current_file = line[4:].strip()
            if current_file not in edits:
                edits[current_file] = []
            if verbose:
                print(f"  📁 Found file: {current_file}")
        elif line.strip() == "<<<<<<< SEARCH":
            search_lines = []
            i += 1
            while i < len(lines) and lines[i].strip() != "=======":
                search_lines.append(lines[i])
                i += 1
            search_text = "\n".join(search_lines)
            i += 1  # skip =======
            replace_lines = []
            while i < len(lines) and lines[i].strip() != ">>>>>>> REPLACE":
                replace_lines.append(lines[i])
                i += 1
            replace_text = "\n".join(replace_lines)
            if current_file:
                edits[current_file].append((search_text, replace_text))
                if verbose:
                    print(f"  📝 Found edit: {len(search_text)} chars → {len(replace_text)} chars")
        i += 1
    
    if verbose:
        print(f"\n  Total edits parsed: {sum(len(v) for v in edits.values())}")

    for filepath, file_edits in edits.items():
        if filepath not in file_contents:
            if verbose:
                print(f"  ⚠ File not found: {filepath}")
                print(f"    Available: {list(file_contents.keys())}")
            continue
        
        content = file_contents[filepath]
        applied = False
        
        for search_text, replace_text in file_edits:
            # Check if SEARCH and REPLACE are identical (LLM bug)
            if search_text == replace_text:
                if verbose:
                    print(f"  ⚠ SEARCH == REPLACE (no change) for {filepath}")
                continue
            
            if search_text in content:
                content = content.replace(search_text, replace_text, 1)
                applied = True
                if verbose:
                    print(f"  ✓ Applied edit to {filepath}")
            else:
                if verbose:
                    print(f"  ✗ SEARCH text not found in {filepath}")
                    # print(f"    SEARCH length: {len(search_text)} chars")
                    # Show first 100 chars for debugging
                    # print(f"    SEARCH preview: {search_text[:100]}...")
        
        if applied:
            edited_files.append(filepath)
            new_contents.append(content)
    
    return edited_files, new_contents


def generate_diff(filepath: str, original: str, modified: str) -> str:
    """Generate unified diff."""
    return "\n".join(unified_diff(
        original.split("\n"), modified.split("\n"),
        fromfile=f"a/{filepath}", tofile=f"b/{filepath}", lineterm=""
    ))



def get_file_contents(repo_path: str, files: list) -> dict:
    """Load file contents from repository."""
    contents = {}
    for filepath in files:
        full_path = Path(repo_path) / filepath
          #repo_path / filepath
        if full_path.exists():
            contents[filepath] = full_path.read_text()
    return contents




def generate_v1_patch( #todo ------------------------------------
    state: SpadeState,
    MAX_ITERATIONS: int = 1,
    NUM_SAMPLES: int = 1,
    verbose: bool = True,   
):
    """Generate patches one file at a time for better focus and quality."""
    instance_id = state["bug_context"].bug_id
    pred_files = state["bug_context"].suspicious_files

    repo_path = state["bug_context"].local_repo_path
    file_contents = get_file_contents(repo_path, pred_files)
    
    if not file_contents:
        return {"instance_id": instance_id, "patch": "", "success": False, "error": "No files loaded"}
 

    # FIX PATTERN--------------
    # active_pattern is passed via Send API in graph.py
    active_pattern = state.get("active_pattern", P_UNCONSTRAINED)
    bug_context = state["bug_context"]
    run_id = state.get("thread_id")
    
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=False)
    
    is_unconstrained = active_pattern == P_UNCONSTRAINED
    
    # Normalize pattern info for logging and prompting
    prompts_config = load_prompts()
    pattern_rationale = ""
    if isinstance(active_pattern, dict):
        pattern = active_pattern.get('pattern_id')
        pattern_str = f"{pattern} ({active_pattern.get('scope')})"
        pattern_rationale = active_pattern.get('rationale', "")
    else:
        pattern_str = str(active_pattern)
        pattern = str(active_pattern)
    pattern_description = prompts_config.get("pattern_taxonomy", {}).get(pattern, "")

    log_prefix = "Unconstrained" if is_unconstrained else pattern_str
    specific_agent_name = f"{agent_base_name}-{pattern}"
    log(f"{loop_info_str} {log_prefix} PatchGen working on pattern -> {pattern_str}", specific_agent_name)
    # -------------------------------

    patch_id = f"v1_{uuid.uuid4().hex[:6]}"
    metrics = {}
    raw_telemetry = {}

    all_patches = []
    edited_files = []
    all_generations = []

    agent_config = settings.LLM_AGENTS["patchgen"]
    # client = LLM_Client(agent=specific_agent_name, **agent_config)
    client = OpenRouterClient(api_key=API_KEY, model=LLM_SETTINGS["model"])
    
    # ============== PROCESS EACH FILE SEPARATELY ==============
    for filepath in file_contents.keys():
        print(f"\n🔧 Processing file: {filepath}")
        
        file_content = file_contents[filepath]
        
        # Iterative refinement: keep improving the same file content.
        current_content = file_content

        for iter_idx in range(MAX_ITERATIONS):
            iter_file_context = f"### {filepath}\n"
            iter_file_context += bug_context.file_snippets[filepath]


            refine_instruction = ""
            if iter_idx > 0:
                refine_instruction = (
                    "\n\nRefinement Round Instruction:\n"
                    "You already proposed a previous patch for this file. "
                    "Review the current updated file context and determine whether there is anything else to improve to produce a better patch for the same bug. If no additional change is needed, respond with '# No changes needed'."
                )
            # Explicitly pass the accumulated patch so the model can refine on top of it.
            current_patch = generate_diff(filepath, file_content, current_content).strip()
            if current_patch:
                patch_history = (
                    "\n\nCurrent accumulated patch for this file (already applied):\n"
                    "```diff\n"
                    f"{current_patch}\n"
                    "```\n"
                    "Use this patch history plus the updated file context to decide if another improvement is needed."
                )
            else:
                patch_history = (
                    "\n\nCurrent accumulated patch for this file (already applied):\n"
                    "(none yet)"
                )

            # Format prompts based on unconstrained flag #TODO<<<<<<<<<<<<<<<<<<<<<
            # Format failed patches section
            v1_patches = state.get("v1_patches", [])
            refined_patches = state.get("refined_patches", [])
            failed_patches_history = get_failed_patches_section(prompts_config, v1_patches, refined_patches, "patch_generation", pattern_filter=pattern)
            
            system_prompt = ""
            user_prompt = ""
            if is_unconstrained or not is_unconstrained:
                
                user_prompt = prompts_config["patch_generation_new"]["unconstrained"]["user"].format(
                    issue_text=bug_context.issue_text,
                    error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
                    suspicious_snippets=iter_file_context, #suspicious_snippets,
                    failed_patches_history=failed_patches_history,
                    filepath=filepath
                )  + patch_history + refine_instruction
            else:
                
                user_prompt = prompts_config["patch_generation_new"]["pattern_guided"]["user"].format(
                    issue_text=bug_context.issue_text,
                    error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
                    suspicious_snippets=iter_file_context, #suspicious_snippets,
                    active_pattern=pattern_str,
                    active_pattern_description=pattern_description,
                    active_pattern_rationale=pattern_rationale,
                    failed_patches_history=failed_patches_history,
                    filepath=filepath
                )  + patch_history + refine_instruction

            print(user_prompt)
            temp = random.uniform(TEMPERATURE_RANGE[0], TEMPERATURE_RANGE[1])
            if verbose:
                print(
                    f"  Iteration {iter_idx+1}/{MAX_ITERATIONS} - "
                    f"sample {1}/{NUM_SAMPLES} ..."
                )

            structured_response, metrics, raw_telemetry = client.generate_raw_response(
                                        system_prompt=system_prompt,
                                        user_prompt=user_prompt,
                                        loop_info=loop_info_dict
            )
            # structured_response, metrics, raw_telemetry = "", {}, {} 

            # print(">>>>  response:")
            # print(structured_response)

            raw_output = structured_response
            all_generations.append({
                "file": filepath,
                "iteration": iter_idx + 1,
                "sample": 1,
                "temperature": temp,
                "output": raw_output,
            })

            blocks = extract_python_blocks(raw_output)
            if not blocks:
                if verbose:
                    print("  ⚠ NO CODE BLOCKS found in the response.")
                continue
            
            edited, new_contents = parse_search_replace(blocks[-1], {filepath: current_content})
            if edited and new_contents:
                new_content = new_contents[0]
                if new_content != current_content:
                    current_content = new_content
                    # total_applied_iterations += 1
                    print(f"  ✓ Applied refinement patch in iteration {iter_idx+1}")
                    break

            

        final_file_patch = ""
        if current_content != file_content:
            final_file_patch = generate_diff(filepath, file_content, current_content)
            if final_file_patch.strip():
                edited_files.append(filepath)
                all_patches.append(final_file_patch)
                print(
                    f"  ✓ Finalized patch for {filepath} "
                )

        if not final_file_patch:
            print(f"  ⚠ No valid patch generated for {filepath}")
    
    # Combine all patches
    final_patch = "\n\n".join(all_patches)

    # # Log Telemetry and Patch to DB
    # if run_id and raw_telemetry:
    #     db_logger.log_telemetry(run_id, f"{agent_base_name}_{pattern}", raw_telemetry)
    #     db_logger.log_patch(
    #         patch_id=patch_id,
    #         run_id=run_id,
    #         patch_version=1,
    #         loop_n=state.get("outer_loop_count", 1),
    #         loop_m=state.get("inner_loop_count", 1),
    #         loop_v=1,
    #         pattern=pattern,
    #         rationale=pattern_rationale,
    #         explanation=explanation,
    #         diff=code_diff,
    #         tests_passed=False, #new patch gen, not yet passed
    #         feedback=""
    #     )
 
    patch = PatchCandidate(
        id=patch_id, 
        code_diff=final_patch,
        pattern=pattern,
        rationale=pattern_rationale,
        origin_v1_id=patch_id, # v1 patch is its own origin
        version=1,
        status="pending",
        execution_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
        explanation="None",
    )

    exit(1)
    
    return {
        "v1_patches": [patch],
        "total_metrics": metrics
    }