import requests
import os
from src.utils.logger import log, get_loop_info
import uuid
import yaml
import logging
from pydantic import BaseModel, Field
from src.core.state import SpadeState, PatchCandidate, P_UNCONSTRAINED
from src.core.llm_client2 import Ollama_Client, OpenRouterClient
from src.core.factory import create_llm_client
from src.utils.snippet_extractor import extract_snippet, extract_snippet_fix
from src.core import settings
from src.utils.db_logger import db_logger
from src.utils.prompt_helper import get_failed_patches_section, get_suspicious_locations

from email.mime import text
import json
import os
import shutil
import hashlib
import requests
from difflib import unified_diff
from pathlib import Path

import re
from typing import Dict, List, Tuple, Optional, Set
import random

# ============== Configuration ==============
TEMPERATURE_RANGE = [0.05, 0.3] #TODO what is this for?
agent_base_name = "PatchGen"


def load_prompts():
    with open(settings.PROMPTS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

class PatchGenerationResponse(BaseModel):
    explanation: str = Field(description="Brief explanation of the fix pattern.")
    code_diff: str = Field(description="The generated patch in UNIFIED DIFF format.")


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


def _normalize_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())

def _strip_line_numbers(text: str) -> str:
    """Only strips line numbers if a significant portion of lines follow the pattern."""
    lines = text.splitlines()
    pattern = re.compile(r'^\s*\d+\s*:\s*')
    
    # Safety: Only strip if >50% of non-empty lines match the pattern
    matches = [bool(pattern.match(l)) for l in lines if l.strip()]
    if matches and sum(matches) / len(matches) > 0.5:
        return "\n".join(pattern.sub('', line) for line in lines)
    return text

def _get_indentation_pattern(text: str) -> List[int]:
    indents = []
    for line in text.splitlines():
        if line.strip():
            indents.append(len(line) - len(line.lstrip(' ')))
        else:
            indents.append(0)
    return indents

def _normalize_indentation(text: str, base_indent: int = 0) -> Tuple[str, int]:
    lines = text.splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    if not non_empty_lines:
        return text, 0
    min_indent = min(len(line) - len(line.lstrip(' ')) for line in non_empty_lines)
    normalized_lines = []
    for line in lines:
        if line.strip():
            current_indent = len(line) - len(line.lstrip(' '))
            new_indent = max(0, current_indent - min_indent + base_indent)
            normalized_lines.append(' ' * new_indent + line.lstrip(' '))
        else:
            normalized_lines.append('')
    return "\n".join(normalized_lines), min_indent

def _find_with_indentation_flexibility(
    content: str, 
    search_text: str, 
    start_from: int = 0
) -> Optional[Tuple[int, int, str]]:
    search_text = search_text.strip("\n")
    search_lines = search_text.splitlines()
    if not search_lines:
        return None

    # We only look at content from start_from onwards
    lookup_content = content[start_from:]
    content_lines = lookup_content.splitlines()

    # Strategy 1: Exact match (within the slice)
    idx = lookup_content.find(search_text)
    if idx != -1:
        return start_from + idx, start_from + idx + len(search_text), search_text
    
    # Strategy 2: Normalized Indentation Match
    search_norm, _ = _normalize_indentation(search_text)
    for i in range(len(content_lines) - len(search_lines) + 1):
        candidate_lines = content_lines[i : i + len(search_lines)]
        candidate = "\n".join(candidate_lines)
        candidate_norm, _ = _normalize_indentation(candidate)
        if search_norm == candidate_norm:
            # Calculate absolute position in the original string
            pre_gap = "\n".join(content_lines[:i])
            start = start_from + (len(pre_gap) + 1 if pre_gap else 0)
            return start, start + len(candidate), candidate

    return None

def _apply_replacement_with_indentation(content: str, search_text: str, replace_text: str, 
                                        start: int, end: int, matched_text: str) -> str:
    """Apply replacement while preserving the file's original indentation style."""
    file_indents = _get_indentation_pattern(matched_text)
    search_indents = _get_indentation_pattern(search_text)
    if file_indents and search_indents:
        indent_offset = file_indents[0] - search_indents[0]
    else:
        indent_offset = 0
    
    if indent_offset != 0:
        replace_lines = replace_text.splitlines()
        adjusted_lines = []
        for line in replace_lines:
            if line.strip():
                current_indent = len(line) - len(line.lstrip(' '))
                new_indent = max(0, current_indent + indent_offset)
                adjusted_lines.append(' ' * new_indent + line.lstrip(' '))
            else:
                adjusted_lines.append('')
        replace_text = "\n".join(adjusted_lines)
    
    return content[:start] + replace_text + content[end:]

def parse_multiple_search_replace_with_snippets(
    raw_output: str, 
    file_contents: Dict[str, str], 
    suspicious_snippets: Dict[str, str],
    verbose: bool = True
) -> Tuple[Dict[str, str], Dict[str, str]]:
    
    updated_contents = file_contents.copy()
    updated_snippets = suspicious_snippets.copy()

    # 1. Isolate code blocks from LLM commentary
    # This prevents the parser from seeing filenames in the chat text as markers
    code_blocks = extract_python_blocks(raw_output)
    if not code_blocks:
        # Fallback: if no markdown fences, treat whole output as code
        # But usually, LLMs on these tasks use fences.
        code_blocks = [raw_output]

    # 2. Strict patterns
    # Marker must be a filename at the start of a line
    file_marker_pattern = re.compile(r'^(?:###\s*)?([a-zA-Z0-9_./\-]+\.[a-zA-Z]+)\s*$', re.MULTILINE)
    # Search/Replace block
    block_pattern = re.compile(
        r'<<<<<<<\s*SEARCH\s*?\n(.*?)\n=======\n(.*?)\n>>>>>>>', 
        re.DOTALL
    )

    for block in code_blocks:
        file_matches = list(file_marker_pattern.finditer(block))
        
        for i, match in enumerate(file_matches):
            filepath = match.group(1).strip()
            start_pos = match.end()
            end_pos = file_matches[i + 1].start() if i + 1 < len(file_matches) else len(block)
            file_chunk = block[start_pos:end_pos]

            if filepath not in updated_contents:
                if verbose: print(f"  ⚠ File {filepath} not found.")
                continue

            # Process edits for this file sequentially
            file_text = updated_contents[filepath]
            snippet_text = updated_snippets.get(filepath, "")
            
            # Pointer to ensure we don't match the same text twice
            last_file_idx = 0 
            last_snippet_idx = 0

            for s_raw, r_raw in block_pattern.findall(file_chunk):
                s_clean = _strip_line_numbers(_normalize_whitespace(s_raw))
                r_clean = _strip_line_numbers(_normalize_whitespace(r_raw))

                # --- Update File ---
                match_res = _find_with_indentation_flexibility(file_text, s_clean, start_from=last_file_idx)
                if match_res:
                    f_start, f_end, f_matched = match_res
                    file_text = _apply_replacement_with_indentation(
                        file_text, s_clean, r_clean, f_start, f_end, f_matched
                    )
                    # Move pointer to the end of the new replacement
                    # This handles multiple identical SEARCH blocks correctly
                    last_file_idx = f_start + len(r_clean) 
                    if verbose: print(f"  ✓ Applied to {filepath}")
                else:
                    if verbose: print(f"  ✗ SEARCH not found in {filepath}")

                # --- Update Snippet (if exists) ---
                if snippet_text:
                    snip_res = _find_with_indentation_flexibility(snippet_text, s_clean, start_from=last_snippet_idx)
                    if snip_res:
                        s_start, s_end, s_matched = snip_res
                        snippet_text = _apply_replacement_with_indentation(
                            snippet_text, s_clean, r_clean, s_start, s_end, s_matched
                        )
                        last_snippet_idx = s_start + len(r_clean)

            updated_contents[filepath] = file_text
            if filepath in updated_snippets:
                updated_snippets[filepath] = snippet_text

    return updated_contents, updated_snippets

#-----------------------

def parse_search_replace(block: str, file_contents: dict, repo_path: str, verbose: bool = True) -> tuple[list, list]:
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
                log(f"  📁 Found file: {current_file}", agent_base_name)
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
                    log(f"  📝 Found edit: {len(search_text)} chars → {len(replace_text)} chars", agent_base_name)
        i += 1
    
    if verbose:
        log(f"\n  Total edits parsed: {sum(len(v) for v in edits.values())}", agent_base_name)

    for filepath, file_edits in edits.items():
        filepath = os.path.join(repo_path, filepath)
        if filepath not in file_contents:
            if verbose:
                log(f"  ⚠ File not found: {filepath}", agent_base_name)
                log(f"    Available: {list(file_contents.keys())}", agent_base_name)
            continue
        
        content = file_contents[filepath]
        applied = False
        
        for search_text, replace_text in file_edits:
            # Check if SEARCH and REPLACE are identical (LLM bug)
            if search_text == replace_text:
                if verbose:
                    log(f"  ⚠ SEARCH == REPLACE (no change) for {filepath}", agent_base_name)
                continue
            
            if search_text in content:
                content = content.replace(search_text, replace_text, 1)
                applied = True
                if verbose:
                    log(f"  ✓ Applied edit to {filepath}", agent_base_name)
            else:
                if verbose:
                    log(f"  ✗ SEARCH text not found in {filepath}", agent_base_name)
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

def generate_diff_all(file_contents: dict, new_contents: dict) -> dict:
    """Generate unified diffs for all edited files."""
    diffs = {}
    for filepath, new_content in new_contents.items():
        original_content = file_contents.get(filepath, "")
        diff = generate_diff(filepath, original_content, new_content)
        if diff:
            git_header = f"diff --git a/{filepath} b/{filepath}\n"
            diffs[filepath] = git_header + diff

    return diffs


def get_file_contents(repo_path: str, files: list) -> dict:
    """Load file contents from repository."""
    contents = {}
    for filepath in files:
        full_path = Path(repo_path) / filepath
          #repo_path / filepath
        if full_path.exists():
            contents[filepath] = full_path.read_text()
    return contents



def generate_refined_patch(state: SpadeState,
                           MAX_ITERATIONS: int = 1,
                            NUM_SAMPLES: int = 1,
                            verbose: bool = True, 
    ):
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
        previous_patch_diff = previous_patch.code_diff
        active_pattern = previous_patch.pattern
        pattern_rationale = previous_patch.rationale or ""
        v_now = prev_version + 1 # NOTE: this will make version to be 3 if the same patch has been picked as winner previously
        sample_idx = previous_patch.sample_idx
        log(f"Previous patch found. Generate refined patch from {origin_id} to {previous_patch.id} to v{v_now}_{sample_idx}...", f"{agent_base_name}-{active_pattern}")
    else:
        v_now = 2 # default 
        sample_idx = 1 # default
        previous_patch_diff = ""
        active_pattern = P_UNCONSTRAINED # default for now, may be overwritten at code segment below        
        # Find the v1 base
        for p in v1_patches:
            if p.id == origin_id:
                previous_patch_diff = p.code_diff
                active_pattern = p.pattern
                pattern_rationale = p.rationale or ""
                log(f"No prevous patch found. Generate refined patch from {origin_id} to v{v_now}_{sample_idx}...", f"{agent_base_name}-{active_pattern}")
                break

    # Update version before getting loop info
    temp_state = state.copy()
    temp_state["current_patch_version"] = v_now
    loop_info_str, loop_info_dict = get_loop_info(temp_state, include_inner=True)
    
    specific_agent_name = f"{agent_base_name}-{active_pattern}-{sample_idx}"
    log(f"{loop_info_str} Lineage: origin_id={origin_id} -> Generating v{v_now}_{sample_idx}", specific_agent_name)

    agent_config = settings.LLM_AGENTS["patchgen"]
    print(f">>> Agent Config: {agent_config}")
    client = create_llm_client(
        agent_name=specific_agent_name,
        **agent_config  # unpacks provider, model, temperature, etc.
    )
    prompts_config = load_prompts()

    # Format failed patches section
    failed_patches_history = get_failed_patches_section(prompts_config, v1_patches, refined_patches, "patch_generation", pattern_filter=active_pattern)

    # --- get file contents
    instance_id = state["bug_context"].bug_id
    pred_files = state["bug_context"].suspicious_files

    repo_path = state["bug_context"].local_repo_path
    file_contents = get_file_contents(repo_path, pred_files)

    bug_context = state["bug_context"]
    
    if not file_contents:
        return {"instance_id": instance_id, "patch": "", "success": False, "error": "No files loaded"}

    # Maintain lineage by using the same UUID suffix as the original v1 winner
    if "_" in origin_id:
        suffix = origin_id.split("_")[-1]
    else:
        suffix = uuid.uuid4().hex[:6] # Fallback if ID format is unexpected

    metrics = {}
    raw_telemetry = {}
    pattern_id = active_pattern[:2].lower() # take the first 2 chars of pattern id
    patch_id = f"v{v_now}_{sample_idx}_{pattern_id}_{suffix}"

    all_patches = []

    # Iterative refinement: keep improving the same file content.
    current_content = file_contents.copy()
    current_snippets = bug_context.file_snippets.copy()
    

    for iter_idx in range(MAX_ITERATIONS):
        
        # # ✅ REBUILD and UPDATE current snippets from current_content
        # snippets_text = ""
        # for file in bug_context.suspicious_files:
        #     snippet = current_snippets.get(file)
        #     snippets_text += f"\nFile: {file}\n{snippet}\n"



        # refine_instruction = ""
        # if iter_idx > 0:
        #     refine_instruction = (
        #         "\n\nRefinement Round Instruction:\n"
        #         "You already proposed a previous patch for this file. "
        #         "Review the current updated file context and determine whether there is anything else to improve to produce a better patch for the same bug. If no additional change is needed, respond with '# No changes needed'."
        #     )
        # # Explicitly pass the accumulated patch so the model can refine on top of it.
        # current_diffs = generate_diff_all(file_contents, current_content)
        
        # current_patch = "\n\n".join(current_diffs.values()).strip() # stringify the dict of diffs
        # if current_patch:
        #     patch_history = (
        #         "\n\nCurrent accumulated patch for this file (already applied):\n"
        #         "```diff\n"
        #         f"{current_patch}\n"
        #         "```\n"
        #         "Use this patch history plus the updated file context to decide if another improvement is needed."
        #     )
        # else:
        #     patch_history = (
        #         "\n\nCurrent accumulated patch for this file (already applied):\n"
        #         "(none yet)"
        #     )



        # Format prompts based on unconstrained flag #TODO<<<<<<<<<<<<<<<<<<<<<
        # Format failed patches section
        
        system_prompt = "" # TODO not used?
        pattern_description = prompts_config.get("pattern_taxonomy", {}).get(active_pattern, "")
        user_prompt = prompts_config["patch_generation_new"]["refinement"]["user"].format(
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
        # user_prompt += patch_history + refine_instruction

        # print(user_prompt)
        temperature = random.uniform(TEMPERATURE_RANGE[0], TEMPERATURE_RANGE[1]) #TODO what is this for? not used anywhere
        client.temperature = temperature 

        try:
            structured_response, metrics, raw_telemetry = client.generate_text(
                                        system_prompt=system_prompt,
                                        user_prompt=user_prompt,
                                        loop_info=loop_info_dict
            )
        except Exception as e:
            log(f"{loop_info_str} Error generating refined patch: {e}", specific_agent_name, level=logging.ERROR)
            return {
                "resolution_status": ["patchgen_failed"],
                "total_metrics": metrics
            }
        # structured_response, metrics, raw_telemetry = "", {}, {} 

        raw_output = structured_response

        if raw_output is None:
            log("  raw_output is None.",  specific_agent_name)
            continue
            
        updated_contents, updated_snippets = parse_multiple_search_replace_with_snippets(raw_output, current_content, verbose=verbose, suspicious_snippets=current_snippets)

        if updated_contents != current_content:
            current_content = updated_contents
            current_snippets = updated_snippets
            log(f"  ✓ APPLIED patch in iteration {iter_idx+1}", specific_agent_name)
        else:
            log(f"  ⚠ NO valid patch generated", specific_agent_name)

    # -----------------------------
        
    # Compare original file_contents to current_content after all iterations
    current_diffs = generate_diff_all(file_contents, current_content)
    all_patches = [diff for diff in current_diffs.values() if diff.strip()]
    
    # Combine all patches
    final_patch = "\n\n".join(all_patches)


    explanation = "<skip>"
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
            diff=final_patch,
            tests_passed=False, #new patch gen, not yet passed
            feedback=state.get("verdict")
        )

    patch = PatchCandidate(
        id=patch_id, 
        sample_idx=sample_idx,
        code_diff=final_patch,
        pattern=active_pattern,
        rationale=pattern_rationale,
        origin_v1_id=origin_id,
        version=v_now,
        status="pending",
        explanation=explanation,
        loop_n=state.get("outer_loop_count", 1),
    )

    return {
        "refined_patches": [patch],
        "current_patch_version": v_now, # Sync the global state counter
        "total_metrics": metrics
    }



def generate_v1_patch_wo_randomRestart( #todo ------------------------------------
    state: SpadeState,
    MAX_ITERATIONS: int = 2,
    NUM_SAMPLES: int = 1,
    verbose: bool = True,   
):
    """Generate patches one file at a time for better focus and quality."""
    instance_id = state["bug_context"].bug_id
    pred_files = [file for file in state["bug_context"].file_snippets.keys()]

    repo_path = state["bug_context"].local_repo_path
    file_contents = get_file_contents(repo_path, pred_files)
    
    if not file_contents:
        return {"instance_id": instance_id, "patch": "", "success": False, "error": "No files loaded"}
 

    # FIX PATTERN--------------
    # active_pattern is passed via Send API in graph.py
    active_pattern = state.get("active_pattern", P_UNCONSTRAINED)
    print(f">>> Active Pattern: {active_pattern}")
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
    sample_idx = state.get("sample_index")
    specific_agent_name = f"{agent_base_name}-{pattern}-{sample_idx}"
    log(f"{loop_info_str} {log_prefix} PatchGen working on pattern -> {pattern_str}", specific_agent_name)
    # -------------------------------

    pattern_id = pattern[:2].lower() # take the first 2 chars of pattern id
    patch_id = f"v1_{sample_idx}_{pattern_id}_{uuid.uuid4().hex[:6]}"
    metrics = {}
    raw_telemetry = {}

    all_patches = []
    edited_files = []

    agent_config = settings.LLM_AGENTS["patchgen"]
    # client = OpenRouterClient(agent=specific_agent_name, **agent_config)
    print(f">>> Agent Config: {agent_config}")
    client = create_llm_client(
        agent_name=specific_agent_name,
        **agent_config  # unpacks provider, model, temperature, etc.
    )
    # client = LLM_Client(agent=specific_agent_name, **agent_config)


    # suspicious_snippets = ""
    
    # for file in bug_context.suspicious_files:
    #     snippet = bug_context.file_snippets.get(file)
    #     suspicious_snippets += f"\nFile: {file}\n{snippet}\n"

    # # If pattern has GLOBAL scope and an upstream file, include it too
    # if isinstance(active_pattern, dict) and active_pattern.get("scope") == "GLOBAL" and active_pattern.get("upstream"):
    #     upstream_file = active_pattern.get("upstream")
    #     log(f"{loop_info_str} {log_prefix} Including upstream context: {upstream_file}", specific_agent_name)
    #     snippet = extract_snippet(
    #         repo_path=bug_context.local_repo_path,
    #         relative_file_path=upstream_file
    #     )
    #     suspicious_snippets += f"\nUpstream File Context: {upstream_file}\n{snippet}\n"

    # if not suspicious_snippets:
    #     suspicious_snippets = "No code snippets available."

            
    # Iterative refinement: keep improving the same file content.
    current_content = file_contents.copy()
    current_snippets = bug_context.file_snippets.copy()

    for iter_idx in range(MAX_ITERATIONS):

        # ✅ REBUILD and UPDATE current snippets from current_content
        snippets_text = ""
        for file in bug_context.suspicious_files:
            snippet = current_snippets.get(file)
            snippets_text += f"\nFile: {file}\n{snippet}\n"
            
        # refine_instruction = ""
        # if iter_idx > 0:
        #     refine_instruction = (
        #         "\n\nRefinement Round Instruction:\n"
        #         "You already proposed a previous patch for this file. "
        #         "Review the current updated file context and determine whether there is anything else to improve to produce a better patch for the same bug. If no additional change is needed, respond with '# No changes needed'."
        #     )
        # # Explicitly pass the accumulated patch so the model can refine on top of it.
        # current_diffs = generate_diff_all(file_contents, current_content)
        # current_patch = "\n\n".join(current_diffs.values()).strip() # stringify the dict of diffs
        # if current_patch:
        #     patch_history = (
        #         "\n\nCurrent accumulated patch for this file (already applied):\n"
        #         "```diff\n"
        #         f"{current_patch}\n"
        #         "```\n"
        #         "Use this patch history plus the updated file context to decide if another improvement is needed."
        #     )
        # else:
        #     patch_history = (
        #         "\n\nCurrent accumulated patch for this file (already applied):\n"
        #         "(none yet)"
        #     )

        # Format prompts based on unconstrained flag #TODO<<<<<<<<<<<<<<<<<<<<<
        # Format failed patches section
        v1_patches = state.get("v1_patches", [])
        refined_patches = state.get("refined_patches", [])
        failed_patches_history = get_failed_patches_section(prompts_config, v1_patches, refined_patches, "patch_generation", pattern_filter=pattern)
        
        system_prompt = "" # TODO not used?
        user_prompt = ""
        if is_unconstrained:
            
            user_prompt = prompts_config["patch_generation_new"]["unconstrained"]["user"].format(
                issue_text=bug_context.issue_text,
                # error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
                suspicious_snippets=snippets_text, 
                failed_patches_history=failed_patches_history,
            )  #+ patch_history + refine_instruction
        else:
            
            user_prompt = prompts_config["patch_generation_new"]["pattern_guided"]["user"].format(
                issue_text=bug_context.issue_text,
                # error_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
                suspicious_snippets=snippets_text, 
                active_pattern=pattern_str,
                active_pattern_description=pattern_description,
                active_pattern_rationale=pattern_rationale,
                failed_patches_history=failed_patches_history,
            )  #+ patch_history + refine_instruction

        temperature = random.uniform(TEMPERATURE_RANGE[0], TEMPERATURE_RANGE[1]) #TODO what is this for? not used anywhere
        if verbose:
            log(
                f"  Iteration {iter_idx+1}/{MAX_ITERATIONS} - "
                f"sample {1}/{NUM_SAMPLES} ...", specific_agent_name
            )

        client.temperature = temperature  # Set temperature for this generation
        structured_response, metrics, raw_telemetry = client.generate_text(
                                    system_prompt=system_prompt,
                                    user_prompt=user_prompt,
                                    loop_info=loop_info_dict
        )
        # structured_response, metrics, raw_telemetry = "", {}, {} 


        raw_output = structured_response

        if raw_output is None:
            log("  raw_output is None.",  specific_agent_name)
            continue
            
        updated_contents, updated_snippets = parse_multiple_search_replace_with_snippets(raw_output, current_content, verbose=verbose, suspicious_snippets=current_snippets)

        

        if updated_contents != current_content:
            current_content = updated_contents
            current_snippets = updated_snippets
            log(f"  ✓ APPLIED patch in iteration {iter_idx+1}", specific_agent_name)
        else:
            log(f"  ⚠ NO valid patch generated", specific_agent_name)
    
    # Compare original file_contents to current_content after all iterations
    current_diffs = generate_diff_all(file_contents, current_content)
    all_patches = [diff for diff in current_diffs.values() if diff.strip()]
    
    # Combine all patches
    final_patch = "\n\n".join(all_patches)

    explanation = "<skip>"
    # # Log Telemetry and Patch to DB
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
            diff=final_patch,
            tests_passed=False, #new patch gen, not yet passed
            feedback=""
        )
 
    patch = PatchCandidate(
        id=patch_id, 
        sample_idx=sample_idx,
        code_diff=final_patch,
        pattern=pattern,
        rationale=pattern_rationale,
        origin_v1_id=patch_id, # v1 patch is its own origin
        version=1,
        status="pending",
        execution_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
        explanation=explanation,
        loop_n=state.get("outer_loop_count", 1),
    )
    
    return {
        "v1_patches": [patch],
        "total_metrics": metrics
    }



def generate_v1_patch( 
    state: SpadeState,
    # MAX_ITERATIONS: int = 3,
    NUM_SAMPLES: int = 4,
    MAX_ATTEMPTS: int = 8,
    ORIGINAL_START_PROB = 0.35,
    verbose: bool = True,   
):
    """Generate patches one file at a time for better focus and quality."""
    instance_id = state["bug_context"].bug_id
    pred_files = list(state["bug_context"].file_snippets.keys())

    repo_path = state["bug_context"].local_repo_path
    file_contents = get_file_contents(repo_path, pred_files)
    
    if not file_contents:
        return {"instance_id": instance_id, "patch": "", "success": False, "error": "No files loaded"}

    # FIX PATTERN--------------
    active_pattern = state.get("active_pattern", P_UNCONSTRAINED)
    bug_context = state["bug_context"]
    run_id = state.get("thread_id")
    
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=False)
    is_unconstrained = active_pattern == P_UNCONSTRAINED
    
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
    # specific_agent_name = f"{agent_base_name}-{pattern}"
    sample_idx = state.get("sample_index") # state variable added by graph.py/activate_patchgen_agents
    specific_agent_name = f"{agent_base_name}-{pattern}-{sample_idx}"    
    log(f"{loop_info_str} {log_prefix} PatchGen working on pattern -> {pattern_str}", specific_agent_name)
    # -------------------------------

    metrics = {}
    raw_telemetry = {}

    agent_config = settings.LLM_AGENTS["patchgen"]
    print(f">>> Agent Config: {agent_config}")
    client = create_llm_client(
        agent_name=specific_agent_name,
        **agent_config 
    )

    # ---------------------------------------------------------
    # METAHEURISTIC SETUP: Initialize candidate pool with the original code.
    # ---------------------------------------------------------
    candidate_pool = [{
        "content": file_contents.copy(),
        "snippets": bug_context.file_snippets.copy(),
        "is_original": True
    }]
    
    all_unique_contents = [] # Stores successfully modified, unique file states
    attempt = 0
    
    # Run until we find NUM_SAMPLES diverse patches or exhaust MAX_ATTEMPTS
    while len(all_unique_contents) < NUM_SAMPLES and attempt < MAX_ATTEMPTS:
        attempt += 1
        log(f"\n-- ({specific_agent_name}) ATTEMPT {attempt}/{MAX_ATTEMPTS} to generate valid patches (Found: {len(all_unique_contents)}/{NUM_SAMPLES})...", specific_agent_name)

        # --- RANDOM RESTART ---
        # Select a random starting state from our pool (includes the original unpatched code)
        # start_state = random.choice(candidate_pool)
        if random.random() < ORIGINAL_START_PROB:
            start_state = candidate_pool[0]
            log("  [Restart] Starting fresh from original code.", specific_agent_name)
        else:
            start_state = random.choice(candidate_pool)
            if start_state.get("is_original"):
                log("  [Restart] Selected original code from pool.", specific_agent_name)
            else:
                log("  [Restart] Picking a previously discovered mutation to refine.", specific_agent_name)



        current_content = start_state["content"].copy()
        current_snippets = start_state["snippets"].copy()
        is_original = start_state.get("is_original")


        snippets_text = ""
        for file in pred_files:
            snippet = current_snippets.get(file)
            snippets_text += f"\nFile: {file}\n{snippet}\n"
            

        v1_patches_history = state.get("v1_patches", [])
        refined_patches_history = state.get("refined_patches", [])
        failed_patches_history = get_failed_patches_section(prompts_config, v1_patches_history, refined_patches_history, "patch_generation", pattern_filter=pattern)
        
        system_prompt = "" 
        
        if is_unconstrained:
            user_prompt = prompts_config["patch_generation_new"]["unconstrained"]["user"].format(
                issue_text=bug_context.issue_text,
                # error_trace="No trace available.",
                suspicious_snippets=snippets_text, 
                failed_patches_history=failed_patches_history,
            ) 
        else:
            user_prompt = prompts_config["patch_generation_new"]["pattern_guided"]["user"].format(
                issue_text=bug_context.issue_text,
                # error_trace="No trace available.",
                suspicious_snippets=snippets_text, 
                active_pattern=pattern_str,
                active_pattern_description=pattern_description,
                active_pattern_rationale=pattern_rationale,
                failed_patches_history=failed_patches_history,
            ) 
        
        if not is_original:
            user_prompt += " If you cannot think of any valid patch, respond with '# No more valid patches'."

        # Random temperature inherently helps the restart logic explore distinct paths
        temperature = random.uniform(TEMPERATURE_RANGE[0], TEMPERATURE_RANGE[1])

        client.temperature = temperature 
        structured_response, attempt_metrics, attempt_telemetry = client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            loop_info=loop_info_dict
        )
        
        # Aggregate metrics
        metrics.update(attempt_metrics)
        raw_telemetry.update(attempt_telemetry)

        raw_output = structured_response

        if raw_output is None:
            log("  raw_output is None.", specific_agent_name)
            continue
            
        updated_contents, updated_snippets = parse_multiple_search_replace_with_snippets(
            raw_output, current_content, verbose=verbose, suspicious_snippets=current_snippets
        )

        if updated_contents != current_content:
            current_content = updated_contents
            current_snippets = updated_snippets

            # --- EVALUATE ATTEMPT & UPDATE POOLS ---
            if current_content != file_contents:
                # Did we discover a brand new patch state?
                if current_content not in all_unique_contents:
                    all_unique_contents.append(current_content)
                    log(f"  ⭐ Discovered new unique patch! (Total distinct patches: {len(all_unique_contents)})", specific_agent_name)
                
                # Add this mutated state to the candidate pool to allow future random restarts to build on it
                if current_content not in [c["content"] for c in candidate_pool]:
                    candidate_pool.append({
                        "content": current_content.copy(),
                        "snippets": current_snippets.copy(),
                        "is_original": False
                    })
    
    if len(all_unique_contents) == 0:
        log(f"   [ERROR] NO valid patch generated after {MAX_ATTEMPTS} attempts.", specific_agent_name)
        # Fallback to the original file contents if everything failed
        all_unique_contents.append(file_contents)

    # ---------------------------------------------------------
    # PACKAGE FINAL PATCHES
    # ---------------------------------------------------------
    final_v1_patches = []
    explanation = "<skip>"

    for content_variant in all_unique_contents:
        current_diffs = generate_diff_all(file_contents, content_variant)
        diff_list = [diff for diff in current_diffs.values() if diff.strip()]
        final_patch = "\n\n".join(diff_list)

        # Skip empty patches unless it's our only fallback
        if not final_patch and len(all_unique_contents) > 1:
            continue

        pattern_id = pattern[:2].lower() # take the first 2 chars of pattern id
        patch_id = f"v1_{sample_idx}_{pattern_id}_{uuid.uuid4().hex[:6]}"
        # patch_id = f"v1_{uuid.uuid4().hex[:6]}"

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
                diff=final_patch,
                tests_passed=False, 
                feedback=""
            )
     
        patch = PatchCandidate(
            id=patch_id, 
            sample_idx=sample_idx,
            code_diff=final_patch,
            pattern=pattern,
            rationale=pattern_rationale,
            origin_v1_id=patch_id,
            version=1,
            status="pending",
            execution_trace=bug_context.error_trace if bug_context.error_trace else "No trace available.",
            explanation=explanation,
        )
        final_v1_patches.append(patch)
    
    return {
        "v1_patches": final_v1_patches,
        "total_metrics": metrics
    }