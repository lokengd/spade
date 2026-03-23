import json
import yaml
from pydantic import BaseModel
from src.core.state import SpadeState
from src.core.llm_client import LLM_Client
from src.utils.logger import log, get_loop_info
from src.core import settings
from src.utils.db_logger import db_logger
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
# Prompt Loading
# ---------------------------------------------------------------------------

def _load_prompts():
    with open(settings.PROMPTS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_candidates_block(v1_patches: list) -> str:
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
    if patch is None:
        return {"id": "none", "pattern": "none", "code_diff": "(none)",
                "execution_trace": "(none)", "origin_v1_id": "unknown"}
    if isinstance(patch, dict):
        return {
            "id": patch.get("id", "?"),
            "pattern": patch.get("pattern", "?"),
            "code_diff": patch.get("code_diff", "(empty)") or "(empty)",
            "execution_trace": patch.get("execution_trace", "(none)") or "(none)",
            "origin_v1_id": patch.get("origin_v1_id", "unknown"),
        }
    return {
        "id": getattr(patch, "id", "?"),
        "pattern": getattr(patch, "pattern", "?"),
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

# def _parse_verdict_from_text(raw_text: str) -> JudgeVerdict:
#     """Parse a JudgeVerdict from raw LLM text output. 
#     Strips markdown fences and attempts JSON parsing."""
#     cleaned = raw_text.strip()
#     # Strip markdown code fences if present
#     if cleaned.startswith("```"):
#         # Remove opening fence (```json or ```)
#         first_newline = cleaned.index("\n")
#         cleaned = cleaned[first_newline + 1:]
#     if cleaned.endswith("```"):
#         cleaned = cleaned[:-3].strip()
    
#     parsed = json.loads(cleaned)
#     return JudgeVerdict(**parsed)

def run(state: SpadeState):
    prompts = _load_prompts()
    loop_info_str, loop_info_dict = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    bug_kwargs = _build_bug_context_kwargs(state)
    v1_patches = state.get("v1_patches", [])
    candidates_block = _format_candidates_block(v1_patches)
    run_id = state.get("thread_id")

    # Shared debate context
    debate_kwargs = {
        "dynamic_argument": state.get("dynamic_argument", "(none)"),
        "static_argument": state.get("static_argument", "(none)"),
        "dynamic_rebuttal": state.get("dynamic_rebuttal", "(none)"),
        "static_rebuttal": state.get("static_rebuttal", "(none)"),
    }

    if v == 1:
        log(f"{loop_info_str} Selecting winner from v1 pool and issuing improvement instructions.", agent_name)
        system_prompt = prompts["judge_select"]["system"]
        user_prompt = prompts["judge_select"]["user"].format(
            candidates_block=candidates_block,
            **bug_kwargs,
            **debate_kwargs,
        )
    else:
        log(f"{loop_info_str} Evaluating failed v{v} patch. Issuing refinement verdict.", agent_name)
        refined_patches = state.get("refined_patches", [])
        pf = _get_patch_fields(refined_patches[-1] if refined_patches else None)
        system_prompt = prompts["judge_refine"]["system"].format(version=v)
        user_prompt = prompts["judge_refine"]["user"].format(
            version=v,
            patch_id=pf["id"],
            patch_pattern=pf["pattern"],
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
    agent_config = settings.LLM_AGENTS["judge"]
    client = LLM_Client(agent=agent_name, **agent_config)
    metrics = {}
    raw_telemetry = {}

    try:
        verdict, metrics, raw_telemetry = client.generate_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=JudgeVerdict,
            loop_info=loop_info_dict
        )
    except Exception as e:
        # Try to salvage from raw response with key remapping
        log(f"Judge structured parse failed: {e}. Attempting key remapping.", agent_name, level=logging.WARNING)
        try:
            raw = raw_telemetry.get("response", {}) if raw_telemetry else {}
            if not isinstance(raw, dict):
                raw = json.loads(str(raw)) if raw else {}
            remapped = {
                "winning_patch_id": raw.get("winning_patch_id") or raw.get("judge_decision") or raw.get("winning_patch") or raw.get("winner") or "",
                "improvement_instructions": raw.get("improvement_instructions") or raw.get("reasoning") or raw.get("instructions") or "",
                "justification": raw.get("justification") or raw.get("reasoning") or raw.get("rationale") or "",
            }
            verdict = JudgeVerdict(**remapped)
        except Exception:
            # True fallback
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

    log(f"{loop_info_str} Verdict: winner={validated_id}, instructions={verdict.improvement_instructions[:80]}...", agent_name)

    # If no winner was found even after fallback, signal failure to skip refinement
    if validated_id == "unknown":
        return _handle_judge_failure(state, metrics)

    # NOTE: current_patch_version is NOT set here. test_agent._handle_fallback
    # is the sole owner of version numbering to avoid double-increment.
    return {
        "verdict": verdict_str,
        "historical_verdicts": [verdict_str],
        "current_v1_id": validated_id,
        "total_metrics": metrics,
    }

def _handle_judge_failure(state: SpadeState, metrics: dict):
    """
    Handles Judge failure by deciding whether to try another winner (M+1) or new patterns (N+1).
    Matches the logic in test_agent._handle_fallback.
    """
    run_id = state.get("thread_id")
    curr_m = state.get("inner_loop_count", 1)
    curr_n = state.get("outer_loop_count", 1)

    # Inner helper to update the DB
    def _update_db_status(status: str = "failed"):
        if run_id:
            db_logger.update_repair_run(
                run_id=run_id,
                fl_match=False, 
                is_resolved=False,
                status=status
            )
            return status
        return "failed"

    # Case 1: Try next winner (pick a new one in next Debate)?
    if curr_m < settings.M_INNER_LOOPS:
        log(f"Judge failed to find winner. Backtracking to pick a NEW winner (Attempt {curr_m + 1}/{settings.M_INNER_LOOPS}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status("judge_failed")], 
            "inner_loop_count": curr_m + 1,
            "current_patch_version": 1,
            "total_metrics": metrics
        }

    # Case 2: Try next patterns?
    if curr_n < settings.N_OUTER_LOOPS:
        log(f"Judge failed and M={settings.M_INNER_LOOPS} hit. Resetting to Pattern Selection (N={curr_n + 1}).", agent_name, level=logging.WARNING)
        return {
            "resolution_status": [_update_db_status("judge_failed")], 
            "inner_loop_count": 1,
            "outer_loop_count": curr_n + 1,
            "current_patch_version": 1,
            "total_metrics": metrics
        }

    # Case 3: All limits hit
    log(f"Judge failed and all limits hit (N={curr_n}, M={curr_m}). Hard stop.", agent_name, level=logging.WARNING)
    return {
        "resolution_status": [_update_db_status("judge_failed")],
        "total_metrics": metrics
    }
