import logging
from src.core.state import SpadeState, get_loop_info

logger = logging.getLogger(__name__)

def run(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    v_next = v + 1

    logger.info(f"[Judge Agent] {loop_info} Issuing verdict to proceed to patch version {v_next}.")
    verdict = f"Winning patch is dynamic_patch_v{v} because <justification>. Proceed to generate patch v{v_next}."
        
    return {
        "verdict": verdict, 
        "historical_verdicts": [verdict],
        "current_patch_version": v_next
    }

