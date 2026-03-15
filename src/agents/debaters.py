import json
from src.core.state import SpadeState
from src.core.llm_client import LLM_Client
from src.utils.logger import log, get_loop_info
from src.core.settings import LLM_AGENTS
from src.utils.db_logger import db_logger
import logging

agent_name_dynamic = "Debater:Dynamic"
agent_name_static = "Debater:Static"

# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

# Mode 1: v==1 -> selecting best candidate from v1 pool
_DYNAMIC_ARG_SELECT_SYSTEM = (
    "You are the Dynamic Debater in an Automated Program Repair pipeline.\n"
    "Your role is to evaluate patch candidates from a RUNTIME perspective.\n\n"
    "Analyze each candidate on:\n"
    "1. Does the patch directly address the observed error trace?\n"
    "2. Does it handle edge cases that could trigger the same class of failure?\n"
    "3. What is the regression risk -- could this patch break passing tests?\n"
    "4. Is the fix minimal and targeted, or does it mask the root cause?\n\n"
    "You will receive the bug context (issue description, error trace, suspicious files)\n"
    "and a list of v1 patch candidates with their diffs and strategies.\n\n"
    "Respond ONLY with valid JSON matching this schema:\n"
    "{{\n"
    '  "recommended_patch_id": "<id of the patch you favor>",\n'
    '  "argument": "<your detailed runtime-focused analysis justifying this choice, '
    'referencing specific patches by ID>"\n'
    "}}"
)

_DYNAMIC_ARG_SELECT_USER = (
    "Bug ID: {bug_id}\n"
    "Issue: {issue_text}\n"
    "Error Trace: {error_trace}\n"
    "Suspicious Files: {suspicious_files}\n\n"
    "v1 Patch Candidates:\n{candidates_block}"
)

# Mode 2: v>=2 -> evaluating a failed refined patch
_DYNAMIC_ARG_REFINE_SYSTEM = (
    "You are the Dynamic Debater in an Automated Program Repair pipeline.\n"
    "A refined patch (v{version}) has just FAILED verification.\n"
    "Your role is to analyze the failure from a RUNTIME perspective.\n\n"
    "Analyze:\n"
    "1. What does the execution trace reveal about why the patch failed?\n"
    "2. Is this a regression (broke passing tests) or an incomplete fix (did not fix the failing test)?\n"
    "3. What specific runtime behavior must the next version address?\n"
    "4. Given the history of prior verdicts and failures, what pattern of mistakes is emerging?\n\n"
    "Respond ONLY with valid JSON:\n"
    "{{\n"
    '  "argument": "<your detailed runtime analysis of the failure and concrete suggestions '
    'for the next patch version>"\n'
    "}}"
)

_DYNAMIC_ARG_REFINE_USER = (
    "Bug ID: {bug_id}\n"
    "Issue: {issue_text}\n"
    "Error Trace (original): {error_trace}\n\n"
    "Failed Patch (v{version}):\n"
    "  ID: {patch_id}\n"
    "  Strategy: {patch_strategy}\n"
    "  Diff:\n{patch_diff}\n"
    "  Execution Trace: {execution_trace}\n\n"
    "Prior Failed Traces: {failed_traces}\n"
    "Prior Verdicts: {historical_verdicts}"
)

# Static debater: structural perspective, same mode split

_STATIC_ARG_SELECT_SYSTEM = (
    "You are the Static Debater in an Automated Program Repair pipeline.\n"
    "Your role is to evaluate patch candidates from a STRUCTURAL / STATIC ANALYSIS perspective.\n\n"
    "Analyze each candidate on:\n"
    "1. Is the diff syntactically correct and minimal (no unnecessary changes)?\n"
    "2. Does the fix align with the declared semantic fix-pattern strategy?\n"
    "3. Does it respect API contracts, type signatures, and module interfaces?\n"
    "4. Are there structural anti-patterns (e.g., swallowed exceptions, dead code, implicit type coercions)?\n\n"
    "You will receive the bug context and a list of v1 patch candidates.\n\n"
    "Respond ONLY with valid JSON:\n"
    "{{\n"
    '  "recommended_patch_id": "<id of the patch you favor>",\n'
    '  "argument": "<your detailed structural analysis justifying this choice, '
    'referencing specific patches by ID>"\n'
    "}}"
)

_STATIC_ARG_SELECT_USER = _DYNAMIC_ARG_SELECT_USER  # Same user context

_STATIC_ARG_REFINE_SYSTEM = (
    "You are the Static Debater in an Automated Program Repair pipeline.\n"
    "A refined patch (v{version}) has just FAILED verification.\n"
    "Your role is to analyze the failure from a STRUCTURAL / STATIC ANALYSIS perspective.\n\n"
    "Analyze:\n"
    "1. Does the diff introduce any syntactic or structural issues?\n"
    "2. Does it violate the API contracts or type expectations of the surrounding code?\n"
    "3. Is the fix-pattern strategy still appropriate, or should a different pattern be tried?\n"
    "4. What structural changes would make the next version more robust?\n\n"
    "Respond ONLY with valid JSON:\n"
    "{{\n"
    '  "argument": "<your detailed structural analysis of the failure and concrete suggestions '
    'for the next patch version>"\n'
    "}}"
)

_STATIC_ARG_REFINE_USER = _DYNAMIC_ARG_REFINE_USER  # Same user context

# Rebuttal prompts -- both modes share the same structure
_DYNAMIC_REBUTTAL_SYSTEM = (
    "You are the Dynamic Debater writing a rebuttal.\n"
    "You have read the Static Debater's argument. Counter their claims using runtime evidence.\n"
    "Where you agree, acknowledge it. Where you disagree, explain why from a runtime behavior perspective.\n"
    "If the Static Debater recommended a different patch than you, argue why yours is better "
    "from a runtime standpoint.\n\n"
    "Respond ONLY with valid JSON:\n"
    "{{\n"
    '  "rebuttal": "<your rebuttal addressing the Static Debater\'s argument point by point>"\n'
    "}}"
)

_DYNAMIC_REBUTTAL_USER = (
    "Your original argument:\n{own_argument}\n\n"
    "Static Debater's argument to rebut:\n{opponent_argument}"
)

_STATIC_REBUTTAL_SYSTEM = (
    "You are the Static Debater writing a rebuttal.\n"
    "You have read the Dynamic Debater's argument. Counter their claims using structural evidence.\n"
    "Where you agree, acknowledge it. Where you disagree, explain why from a code structure perspective.\n"
    "If the Dynamic Debater recommended a different patch than you, argue why yours is better "
    "from a structural standpoint.\n\n"
    "Respond ONLY with valid JSON:\n"
    "{{\n"
    '  "rebuttal": "<your rebuttal addressing the Dynamic Debater\'s argument point by point>"\n'
    "}}"
)

_STATIC_REBUTTAL_USER = (
    "Your original argument:\n{own_argument}\n\n"
    "Dynamic Debater's argument to rebut:\n{opponent_argument}"
)


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
        strategy = p.get("strategy", "?") if isinstance(p, dict) else getattr(p, "strategy", "?")
        diff = p.get("code_diff", "(empty)") if isinstance(p, dict) else getattr(p, "code_diff", "(empty)")
        lines.append(f"--- Candidate {pid} [strategy: {strategy}] ---\n{diff or '(empty diff)'}\n")
    return "\n".join(lines)


def _get_patch_fields(patch) -> dict:
    """Extract fields from a PatchCandidate whether it is a dict or Pydantic model."""
    if patch is None:
        return {"id": "none", "strategy": "none", "code_diff": "(none)", "execution_trace": "(none)"}
    if isinstance(patch, dict):
        return {
            "id": patch.get("id", "?"),
            "strategy": patch.get("strategy", "?"),
            "code_diff": patch.get("code_diff", "(empty)") or "(empty)",
            "execution_trace": patch.get("execution_trace", "(none)") or "(none)",
        }
    return {
        "id": getattr(patch, "id", "?"),
        "strategy": getattr(patch, "strategy", "?"),
        "code_diff": getattr(patch, "code_diff", "(empty)") or "(empty)",
        "execution_trace": getattr(patch, "execution_trace", "(none)") or "(none)",
    }


def _call_llm(caller: str, system_prompt: str, user_prompt: str, loop_info: dict = None, run_id: str = None) -> tuple:
    """LLM call with error handling. Returns (raw_text, metrics)."""
    agent_config = LLM_AGENTS["debaters"]
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
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    bug_kwargs = _build_bug_context_kwargs(state)
    run_id = state.get("thread_id")

    if v == 1:
        log(f"{loop_info_str} Selecting best v1 candidate (runtime analysis).", agent_name_dynamic)
        candidates_block = _format_candidates_block(state.get("v1_patches", []))
        system_prompt = _DYNAMIC_ARG_SELECT_SYSTEM
        user_prompt = _DYNAMIC_ARG_SELECT_USER.format(
            candidates_block=candidates_block, **bug_kwargs
        )
    else:
        log(f"{loop_info_str} Analyzing failed v{v} patch (runtime analysis).", agent_name_dynamic)
        refined_patches = state.get("refined_patches", [])
        pf = _get_patch_fields(refined_patches[-1] if refined_patches else None)
        system_prompt = _DYNAMIC_ARG_REFINE_SYSTEM.format(version=v)
        user_prompt = _DYNAMIC_ARG_REFINE_USER.format(
            version=v,
            patch_id=pf["id"],
            patch_strategy=pf["strategy"],
            patch_diff=pf["code_diff"],
            execution_trace=pf["execution_trace"],
            failed_traces=json.dumps(state.get("failed_traces", [])[-5:]),
            historical_verdicts=json.dumps(state.get("historical_verdicts", [])[-3:]),
            **bug_kwargs,
        )

    raw, metrics = _call_llm(agent_name_dynamic, system_prompt, user_prompt, loop_info=loop_info_dict, run_id=run_id)
    return {"dynamic_argument": raw, "total_metrics": metrics}


def generate_static_arg(state: SpadeState):
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    bug_kwargs = _build_bug_context_kwargs(state)
    run_id = state.get("thread_id")

    if v == 1:
        log(f"{loop_info_str} Selecting best v1 candidate (structural analysis).", agent_name_static)
        candidates_block = _format_candidates_block(state.get("v1_patches", []))
        system_prompt = _STATIC_ARG_SELECT_SYSTEM
        user_prompt = _STATIC_ARG_SELECT_USER.format(
            candidates_block=candidates_block, **bug_kwargs
        )
    else:
        log(f"{loop_info_str} Analyzing failed v{v} patch (structural analysis).", agent_name_static)
        refined_patches = state.get("refined_patches", [])
        pf = _get_patch_fields(refined_patches[-1] if refined_patches else None)
        system_prompt = _STATIC_ARG_REFINE_SYSTEM.format(version=v)
        user_prompt = _STATIC_ARG_REFINE_USER.format(
            version=v,
            patch_id=pf["id"],
            patch_strategy=pf["strategy"],
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
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Writing rebuttal against Static argument.", agent_name_dynamic)
    run_id = state.get("thread_id")

    own_arg = state.get("dynamic_argument", "(no argument recorded)")
    opponent_arg = state.get("static_argument", "(no argument recorded)")

    user_prompt = _DYNAMIC_REBUTTAL_USER.format(
        own_argument=own_arg, opponent_argument=opponent_arg
    )
    raw, metrics = _call_llm(agent_name_dynamic, _DYNAMIC_REBUTTAL_SYSTEM, user_prompt, loop_info=loop_info_dict, run_id=run_id)
    return {"dynamic_rebuttal": raw, "total_metrics": metrics}


def generate_static_rebuttal(state: SpadeState):
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    log(f"{loop_info_str} Writing rebuttal against Dynamic argument.", agent_name_static)
    run_id = state.get("thread_id")

    own_arg = state.get("static_argument", "(no argument recorded)")
    opponent_arg = state.get("dynamic_argument", "(no argument recorded)")

    user_prompt = _STATIC_REBUTTAL_USER.format(
        own_argument=own_arg, opponent_argument=opponent_arg
    )
    raw, metrics = _call_llm(agent_name_static, _STATIC_REBUTTAL_SYSTEM, user_prompt, loop_info=loop_info_dict, run_id=run_id)
    return {"static_rebuttal": raw, "total_metrics": metrics}
