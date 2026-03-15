import json
from pydantic import BaseModel
from src.core.state import SpadeState, get_loop_info
from src.core.llm_client import LLM_Client
from src.utils.logger import log
from config.settings import LLM_AGENTS
import logging

agent_name = "Judge"


# ---------------------------------------------------------------------------
# Structured Output Model (local to judge, not in shared state)
# ---------------------------------------------------------------------------

class JudgeVerdict(BaseModel):
    """Structured output from the Judge agent. Consumed by generate_refined_patch."""
    winning_patch_id: str
    improvement_instructions: str
    justification: str


# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

# Mode 1: v==1 -> judge selects winner from v1 pool after debate
_JUDGE_SELECT_SYSTEM = (
    "You are the Judge in an Automated Program Repair debate panel.\n"
    "Two debaters -- Dynamic (runtime-focused) and Static (structure-focused) -- have argued\n"
    "over which v1 patch candidate best fixes the bug. Each has presented an initial argument\n"
    "and a rebuttal of the other's position.\n\n"
    "Your task:\n"
    "1. Weigh both perspectives. Runtime correctness takes slight priority over structural elegance,\n"
    "   but a patch with serious structural flaws (API contract violations, type errors) should be penalized.\n"
    "2. Select the winning patch from the v1 candidate pool.\n"
    "3. Provide concrete improvement instructions for the PatchGen agent to refine the winner.\n"
    "   These instructions should synthesize the strongest points from BOTH debaters.\n\n"
    "Respond ONLY with valid JSON matching this schema:\n"
    "{{\n"
    '  "winning_patch_id": "<id of the selected v1 patch>",\n'
    '  "improvement_instructions": "<specific, actionable instructions for PatchGen to improve this patch>",\n'
    '  "justification": "<your reasoning, referencing specific debater arguments>"\n'
    "}}"
)

_JUDGE_SELECT_USER = (
    "Bug ID: {bug_id}\n"
    "Issue: {issue_text}\n"
    "Error Trace: {error_trace}\n\n"
    "v1 Patch Candidates:\n{candidates_block}\n\n"
    "=== DYNAMIC DEBATER ===\n"
    "Argument:\n{dynamic_argument}\n\n"
    "Rebuttal:\n{dynamic_rebuttal}\n\n"
    "=== STATIC DEBATER ===\n"
    "Argument:\n{static_argument}\n\n"
    "Rebuttal:\n{static_rebuttal}"
)

# Mode 2: v>=2 -> judge evaluates failed refined patch after debate
_JUDGE_REFINE_SYSTEM = (
    "You are the Judge in an Automated Program Repair debate panel.\n"
    "A refined patch (v{version}) has FAILED verification. Two debaters have analyzed the failure:\n"
    "- Dynamic Debater: runtime perspective\n"
    "- Static Debater: structural perspective\n\n"
    "Your task:\n"
    "1. Synthesize both analyses to determine the root cause of the failure.\n"
    "2. Decide whether to continue refining the current v1 base patch or suggest a different\n"
    "   v1 candidate (by setting winning_patch_id to a different v1 ID).\n"
    "3. Provide concrete, actionable improvement instructions that address the specific failure mode.\n"
    "   Do NOT repeat instructions from prior verdicts -- check the history and escalate specificity.\n\n"
    "Respond ONLY with valid JSON matching this schema:\n"
    "{{\n"
    '  "winning_patch_id": "<id of the v1 patch to continue building on (can change from current)>",\n'
    '  "improvement_instructions": "<specific instructions for the next patch version>",\n'
    '  "justification": "<your reasoning, referencing debater arguments and failure history>"\n'
    "}}"
)

_JUDGE_REFINE_USER = (
    "Bug ID: {bug_id}\n"
    "Issue: {issue_text}\n"
    "Error Trace (original): {error_trace}\n\n"
    "Failed Patch (v{version}):\n"
    "  ID: {patch_id}\n"
    "  Strategy: {patch_strategy}\n"
    "  Built on v1: {origin_v1_id}\n"
    "  Diff:\n{patch_diff}\n"
    "  Execution Trace: {execution_trace}\n\n"
    "Available v1 Candidates:\n{candidates_block}\n\n"
    "=== DYNAMIC DEBATER ===\n"
    "Argument:\n{dynamic_argument}\n\n"
    "Rebuttal:\n{dynamic_rebuttal}\n\n"
    "=== STATIC DEBATER ===\n"
    "Argument:\n{static_argument}\n\n"
    "Rebuttal:\n{static_rebuttal}\n\n"
    "Prior Verdicts: {historical_verdicts}\n"
    "Prior Failed Traces: {failed_traces}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_candidates_block(v1_patches: list) -> str:
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
    if patch is None:
        return {"id": "none", "strategy": "none", "code_diff": "(none)",
                "execution_trace": "(none)", "origin_v1_id": "unknown"}
    if isinstance(patch, dict):
        return {
            "id": patch.get("id", "?"),
            "strategy": patch.get("strategy", "?"),
            "code_diff": patch.get("code_diff", "(empty)") or "(empty)",
            "execution_trace": patch.get("execution_trace", "(none)") or "(none)",
            "origin_v1_id": patch.get("origin_v1_id", "unknown"),
        }
    return {
        "id": getattr(patch, "id", "?"),
        "strategy": getattr(patch, "strategy", "?"),
        "code_diff": getattr(patch, "code_diff", "(empty)") or "(empty)",
        "execution_trace": getattr(patch, "execution_trace", "(none)") or "(none)",
        "origin_v1_id": getattr(patch, "origin_v1_id", "unknown"),
    }


def _build_bug_context_kwargs(state: SpadeState) -> dict:
    bug = state["bug_context"]
    if isinstance(bug, dict):
        return {
            "bug_id": bug.get("bug_id", "?"),
            "issue_text": bug.get("issue_text", "?"),
            "error_trace": bug.get("error_trace") or "No trace available",
        }
    return {
        "bug_id": bug.bug_id,
        "issue_text": bug.issue_text,
        "error_trace": bug.error_trace or "No trace available",
    }


def _validate_winning_patch_id(verdict: JudgeVerdict, v1_patches: list) -> str:
    """Ensure the judge's selected patch ID actually exists in the v1 pool.
    Falls back to the first v1 candidate if the ID is invalid."""
    valid_ids = set()
    for p in v1_patches:
        pid = p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")
        valid_ids.add(pid)

    if verdict.winning_patch_id in valid_ids:
        return verdict.winning_patch_id

    if v1_patches:
        fallback = v1_patches[0].get("id", "?") if isinstance(v1_patches[0], dict) else v1_patches[0].id
        log(
            f"Judge selected invalid patch ID '{verdict.winning_patch_id}'. "
            f"Falling back to first v1 candidate: {fallback}",
            caller=agent_name, level=logging.WARNING
        )
        return fallback

    log("No v1 patches available for fallback. Returning judge's original selection.",
        caller=agent_name, level=logging.ERROR)
    return verdict.winning_patch_id


# ---------------------------------------------------------------------------
# Main Judge Node
# ---------------------------------------------------------------------------

def run(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    bug_kwargs = _build_bug_context_kwargs(state)
    v1_patches = state.get("v1_patches", [])
    candidates_block = _format_candidates_block(v1_patches)

    # Shared debate context
    debate_kwargs = {
        "dynamic_argument": state.get("dynamic_argument", "(none)"),
        "static_argument": state.get("static_argument", "(none)"),
        "dynamic_rebuttal": state.get("dynamic_rebuttal", "(none)"),
        "static_rebuttal": state.get("static_rebuttal", "(none)"),
    }

    if v == 1:
        log(f"{loop_info} Selecting winner from v1 pool and issuing improvement instructions.", agent_name)
        system_prompt = _JUDGE_SELECT_SYSTEM
        user_prompt = _JUDGE_SELECT_USER.format(
            candidates_block=candidates_block,
            **bug_kwargs,
            **debate_kwargs,
        )
    else:
        log(f"{loop_info} Evaluating failed v{v} patch. Issuing refinement verdict.", agent_name)
        refined_patches = state.get("refined_patches", [])
        pf = _get_patch_fields(refined_patches[-1] if refined_patches else None)
        system_prompt = _JUDGE_REFINE_SYSTEM.format(version=v)
        user_prompt = _JUDGE_REFINE_USER.format(
            version=v,
            patch_id=pf["id"],
            patch_strategy=pf["strategy"],
            origin_v1_id=pf["origin_v1_id"],
            patch_diff=pf["code_diff"],
            execution_trace=pf["execution_trace"],
            candidates_block=candidates_block,
            historical_verdicts=json.dumps(state.get("historical_verdicts", [])[-5:]),
            failed_traces=json.dumps(state.get("failed_traces", [])[-5:]),
            **bug_kwargs,
            **debate_kwargs,
        )

    # Call LLM with structured output
    agent_config = LLM_AGENTS["judge"]
    client = LLM_Client(agent=agent_name, **agent_config)
    metrics = {}

    try:
        verdict, metrics = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=JudgeVerdict,
        )
    except Exception as e:
        log(f"Judge LLM call failed: {e}. Generating fallback verdict.", agent_name, level=logging.ERROR)
        fallback_id = "unknown"
        if v1_patches:
            fallback_id = (v1_patches[0].get("id", "unknown")
                          if isinstance(v1_patches[0], dict) else v1_patches[0].id)
        verdict = JudgeVerdict(
            winning_patch_id=fallback_id,
            improvement_instructions="Address the error trace directly. Ensure the fix is minimal and does not introduce regressions.",
            justification="Fallback verdict due to LLM failure.",
        )

    # Validate the winning patch ID against the actual v1 pool
    validated_id = _validate_winning_patch_id(verdict, v1_patches)
    verdict_str = verdict.model_dump_json()

    log(f"{loop_info} Verdict: winner={validated_id}, instructions={verdict.improvement_instructions[:80]}...", agent_name)

    # NOTE: current_patch_version is NOT set here. test_agent._handle_fallback
    # is the sole owner of version numbering to avoid double-increment.
    return {
        "verdict": verdict_str,
        "historical_verdicts": [verdict_str],
        "current_v1_id": validated_id,
        "total_metrics": metrics,
    }
