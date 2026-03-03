from src.utils.logger import log
from src.core.state import SpadeState, get_loop_info

agent_name = "Judge Agent"

def run(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    v_next = v + 1

    log(f"{loop_info} Issuing verdict to proceed to patch version {v_next}.", agent_name)
    verdict = f"Winning patch is dynamic_patch_v{v} because <justification>. Proceed to generate patch v{v_next}."
        
    return {
        "verdict": verdict, 
        "historical_verdicts": [verdict],
        "current_patch_version": v_next
    }

