import json
import yaml
from src.core.state import SpadeState
from src.core.llm_client import LLM_Client
from src.utils.logger import log, get_loop_info
from src.core import settings
from src.utils.db_logger import db_logger
import logging

agent_name_dynamic = "Debater:Dynamic"
agent_name_static = "Debater:Static"


# ---------------------------------------------------------------------------
# Prompt Loading
# ---------------------------------------------------------------------------

def _load_prompts():
    with open(settings.PROMPTS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_candidates_block(v1_patches: list) -> str:
    """Format v1 patch list into a readable block for the prompt."""
    if not v1_patches:
        return "(no candidates available)"
    lines = []
    for p in v1_patches:
        pid = p.get("id", "?") if isinstance(p, dict) else getattr(p, "id", "?")
        pattern = p.get("pattern", "?") if isinstance(p, dict) else getattr(p, "pattern", "?")
        diff = p.get("code_diff", "(empty)") if isinstance(p, dict) else getattr(p, "code_diff", "(empty)")
        lines.append(f"--- Candidate {pid} [pattern: {pattern}] ---\n{diff or '(empty diff)'}\n")
    return "\n".join(lines)


def _get_patch_fields(patch) -> dict:
    """Extract fields from a PatchCandidate whether it is a dict or Pydantic model."""
    if patch is None:
        return {"id": "none", "pattern": "none", "code_diff": "(none)", "execution_trace": "(none)"}
    if isinstance(patch, dict):
        return {
            "id": patch.get("id", "?"),
            "pattern": patch.get("pattern", "?"),
            "code_diff": patch.get("code_diff", "(empty)") or "(empty)",
            "execution_trace": patch.get("execution_trace", "(none)") or "(none)",
        }
    return {
        "id": getattr(patch, "id", "?"),
        "pattern": getattr(patch, "pattern", "?"),
        "code_diff": getattr(patch, "code_diff", "(empty)") or "(empty)",
        "execution_trace": getattr(patch, "execution_trace", "(none)") or "(none)",
    }


def _call_llm(caller: str, system_prompt: str, user_prompt: str, loop_info: dict = None, run_id: str = None) -> tuple:
    """LLM call with error handling. Returns (raw_text, metrics)."""
    agent_config = settings.LLM_AGENTS["debaters"]
    client = LLM_Client(agent=caller, **agent_config)
    try:
        text, metrics, raw_telemetry = client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            loop_info=loop_info
        )
        if run_id and raw_telemetry:
            db_logger.log_telemetry(run_id, caller, raw_telemetry)
        return text, metrics
    except Exception as e:
        log(f"LLM call failed: {e}", caller=caller, level=logging.ERROR)
        return "", {}


def _build_bug_context_kwargs(state: SpadeState) -> dict:
    """Extract common bug context fields for prompt formatting."""
    bug = state["bug_context"]
    if isinstance(bug, dict):
        return {
            "bug_id": bug.get("bug_id", "?"),
            "issue_text": bug.get("issue_text", "?"),
            "error_trace": bug.get("error_trace") or "No trace available",
            "suspicious_files": ", ".join(bug.get("suspicious_files", [])),
        }
    return {
        "bug_id": bug.bug_id,
        "issue_text": bug.issue_text,
        "error_trace": bug.error_trace or "No trace available",
        "suspicious_files": ", ".join(bug.suspicious_files),
    }


# ---------------------------------------------------------------------------
# Phase 1: Parallel Argument Generation
# ---------------------------------------------------------------------------

def generate_dynamic_arg(state: SpadeState):
    prompts = _load_prompts()
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    bug_kwargs = _build_bug_context_kwargs(state)
    run_id = state.get("thread_id")

    if v == 1:
        log(f"{loop_info_str} Selecting best v1 candidate (runtime analysis).", agent_name_dynamic)
        candidates_block = _format_candidates_block(state.get("v1_patches", []))
        system_prompt = prompts["debater_dynamic_arg_select"]["system"]
        user_prompt = prompts["debater_arg_select"]["user"].format(
            candidates_block=candidates_block, **bug_kwargs
        )
    else:
        log(f"{loop_info_str} Analyzing failed v{v} patch (runtime analysis).", agent_name_dynamic)
        refined_patches = state.get("refined_patches", [])
        pf = _get_patch_fields(refined_patches[-1] if refined_patches else None)
        system_prompt = prompts["debater_dynamic_arg_refine"]["system"].format(version=v)
        user_prompt = prompts["debater_arg_refine"]["user"].format(
            version=v,
            patch_id=pf["id"],
            patch_pattern=pf["pattern"],
            patch_diff=pf["code_diff"],
            execution_trace=pf["execution_trace"],
            failed_traces=json.dumps(state.get("failed_traces", [])[-5:]),
            historical_verdicts=json.dumps(state.get("historical_verdicts", [])[-3:]),
            **bug_kwargs,
        )

    raw, metrics = _call_llm(agent_name_dynamic, system_prompt, user_prompt, loop_info=loop_info_dict, run_id=run_id)
    return {"dynamic_argument": raw, "total_metrics": metrics}


def generate_static_arg(state: SpadeState):
    prompts = _load_prompts()
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    bug_kwargs = _build_bug_context_kwargs(state)
    run_id = state.get("thread_id")

    if v == 1:
        log(f"{loop_info_str} Selecting best v1 candidate (structural analysis).", agent_name_static)
        candidates_block = _format_candidates_block(state.get("v1_patches", []))
        system_prompt = prompts["debater_static_arg_select"]["system"]
        user_prompt = prompts["debater_arg_select"]["user"].format(
            candidates_block=candidates_block, **bug_kwargs
        )
    else:
        log(f"{loop_info_str} Analyzing failed v{v} patch (structural analysis).", agent_name_static)
        refined_patches = state.get("refined_patches", [])
        pf = _get_patch_fields(refined_patches[-1] if refined_patches else None)
        system_prompt = prompts["debater_static_arg_refine"]["system"].format(version=v)
        user_prompt = prompts["debater_arg_refine"]["user"].format(
            version=v,
            patch_id=pf["id"],
            patch_pattern=pf["pattern"],
            patch_diff=pf["code_diff"],
            execution_trace=pf["execution_trace"],
            failed_traces=json.dumps(state.get("failed_traces", [])[-5:]),
            historical_verdicts=json.dumps(state.get("historical_verdicts", [])[-3:]),
            **bug_kwargs,
        )

    raw, metrics = _call_llm(agent_name_static, system_prompt, user_prompt, loop_info=loop_info_dict, run_id=run_id)
    return {"static_argument": raw, "total_metrics": metrics}


# ---------------------------------------------------------------------------
# Phase 2: The Exchange (Synchronization Barrier)
# ---------------------------------------------------------------------------

def exchange_arguments(state: SpadeState):
    """No-op sync node. Both arguments are already in state; this node exists
    solely so LangGraph waits for both before fanning out to rebuttals."""
    loop_info_str, _ = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Both arguments received. Exchanging for rebuttals.", "Debate Exchange")
    return {}


# ---------------------------------------------------------------------------
# Phase 3: Parallel Rebuttal Generation
# ---------------------------------------------------------------------------

def generate_dynamic_rebuttal(state: SpadeState):
    prompts = _load_prompts()
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Writing rebuttal against Static argument.", agent_name_dynamic)
    run_id = state.get("thread_id")

    own_arg = state.get("dynamic_argument", "(no argument recorded)")
    opponent_arg = state.get("static_argument", "(no argument recorded)")

    system_prompt = prompts["debater_dynamic_rebuttal"]["system"]
    user_prompt = prompts["debater_dynamic_rebuttal"]["user"].format(
        own_argument=own_arg, opponent_argument=opponent_arg
    )
    raw, metrics = _call_llm(agent_name_dynamic, system_prompt, user_prompt, loop_info=loop_info_dict, run_id=run_id)
    return {"dynamic_rebuttal": raw, "total_metrics": metrics}


def generate_static_rebuttal(state: SpadeState):
    prompts = _load_prompts()
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Writing rebuttal against Dynamic argument.", agent_name_static)
    run_id = state.get("thread_id")

    own_arg = state.get("static_argument", "(no argument recorded)")
    opponent_arg = state.get("dynamic_argument", "(no argument recorded)")

    system_prompt = prompts["debater_static_rebuttal"]["system"]
    user_prompt = prompts["debater_static_rebuttal"]["user"].format(
        own_argument=own_arg, opponent_argument=opponent_arg
    )
    raw, metrics = _call_llm(agent_name_static, system_prompt, user_prompt, loop_info=loop_info_dict, run_id=run_id)
    return {"static_rebuttal": raw, "total_metrics": metrics}
