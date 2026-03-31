from typing import List, Dict
from src.core.state import PatchCandidate, DebateRecord

def format_failed_patches(v1_patches: List[PatchCandidate], refined_patches: List[PatchCandidate], pattern_filter: str = None) -> str:
    """
    Formats failed patches from v1_patches and refined_patches into a readable string for prompts.
    If pattern_filter is provided, only patches matching that pattern are included.
    """
    failed_patches = []
    
    # Collect all patches with "failed" status
    all_candidates = (v1_patches or []) + (refined_patches or [])
    for patch in all_candidates:
        if patch.status == "failed":
            if pattern_filter:
                if patch.pattern == pattern_filter:
                    failed_patches.append(patch)
            else:
                failed_patches.append(patch)
            
    if not failed_patches:
        return "No previously failed patches to report."
        
    formatted_parts = []
    count = 0
    for patch in failed_patches:
        count += 1
        part = f"### {count}. Patch ID: {patch.id}\n"
        part += f"- **Fix-Pattern:** {patch.pattern}\n"
        if patch.rationale:
            part += f"- **Pattern Selection Rationale:** {patch.rationale}\n"
        if patch.explanation:
            part += f"- **Patch Explanation:** {patch.explanation}\n"
        part += f"- **Code Diff:**\n```diff\n{patch.code_diff}\n```\n"
        
        formatted_parts.append(part)
        
    return "\n".join(formatted_parts)

def get_failed_patches_section(prompts_config: Dict, v1_patches: List[PatchCandidate], refined_patches: List[PatchCandidate], section_key: str, pattern_filter: str = None) -> str:
    """
    Returns the formatted 'failed_patches_history' section if there are failed patches, 
    otherwise returns an empty string or a placeholder.
    """
    failed_patches_str = format_failed_patches(v1_patches, refined_patches, pattern_filter=pattern_filter)
    
    if failed_patches_str == "No previously failed patches to report.":
        return ""
        
    inclusion_template = prompts_config[section_key]["failed_patches_history"]
    if not inclusion_template:
        return ""
        
    return inclusion_template.format(failed_patches=failed_patches_str)


def format_debate_history(debate_history: list, limit: int = 3) -> str:
    """
    Formats recent debate records into a readable string for PatchGen prompts.
    Limited to the most recent `limit` records to control prompt size.
    """
    if not debate_history:
        return "No prior debate history."
    
    # Take the most recent records
    recent = debate_history[-limit:]
    
    formatted_parts = []
    for i, record in enumerate(recent):
        r = record if isinstance(record, DebateRecord) else DebateRecord(**record)
        part = f"### Debate Round {i+1} (N={r.loop_n}, M={r.loop_m}, V={r.loop_v})\n"
        part += f"- **Patch Under Review:** {r.patch_id}\n"
        part += f"- **Winner:** {r.winning_patch_id}\n"
        part += f"- **Improvement Instructions:** {r.improvement_instructions}\n"
        part += f"- **Justification:** {r.justification}\n"
        part += f"- **Dynamic Debater Summary:** {r.dynamic_argument[:300]}...\n" if len(r.dynamic_argument) > 300 else f"- **Dynamic Debater:** {r.dynamic_argument}\n"
        part += f"- **Static Debater Summary:** {r.static_argument[:300]}...\n" if len(r.static_argument) > 300 else f"- **Static Debater:** {r.static_argument}\n"
        formatted_parts.append(part)
    
    return "\n".join(formatted_parts)


def get_debate_history_section(prompts_config: dict, debate_history: list, section_key: str) -> str:
    """
    Returns the formatted 'debate_history' section if there are debate records,
    otherwise returns an empty string.
    """
    debate_str = format_debate_history(debate_history)
    
    if debate_str == "No prior debate history.":
        return ""
    
    inclusion_template = prompts_config.get(section_key, {}).get("debate_history_section", "")
    if not inclusion_template:
        return ""
    
    return inclusion_template.format(debate_history=debate_str)

def get_suspicious_locations(bug_context):
    locations_str = ""
    if bug_context.suspicious_files:
        locations_str += "--- Suspicious Files ---\n"
        locations_str += "\n".join([f"- {f}" for f in bug_context.suspicious_files])
        locations_str += "\n"
        
    if bug_context.related_functions:
        locations_str += "\n--- Related Functions ---\n"
        for file, funcs in bug_context.related_functions.items():
            locations_str += f"- {file}: {', '.join(funcs)}\n"
        locations_str += "\n"
            
    if bug_context.edit_locations:
        locations_str += "--- Edit Locations ---\n"
        for loc in bug_context.edit_locations:
            class_str = f" | Class: {loc.classname}" if loc.classname else ""
            func_str = f" | Func: {loc.function}" if loc.function else ""
            lines_str = f" | Lines: {loc.lines}" if loc.lines else ""
            locations_str += f"- File: {loc.file}{class_str}{func_str}{lines_str}\n"

    if not locations_str.strip():
        locations_str = "No specific locations identified by Fault Localization."

    return locations_str.strip()