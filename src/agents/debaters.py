from src.utils.logger import log
from src.core.state import SpadeState, get_loop_info

agent_name = "Debater Agent"

# ==========================================
# Phase 1: Parallel Argument Generation
# ==========================================
def generate_dynamic_arg(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    
    # Inject the dynamic instruction
    if v == 1:
        instruction = "Select the winning patch from v1_patch_candidates for the closest to the real patch."
        log(f"{loop_info} Dynamic: {instruction}", agent_name)
        support_arg = "Support argument: to be reasoned by LLM."
    else:
        log(f"{loop_info} Dynamic: Review why v{v} failed. Debate fix for v{v+1}.", agent_name)
        support_arg = f"Dynamic Debater: to be reasoned by LLM."

    return {"dynamic_argument": support_arg}


def generate_static_arg(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    
    if v == 1:
        instruction = "Select the winning patch from v1_patch_candidates for the closest to the real patch."
        log(f"{loop_info} Static: {instruction}", agent_name)
        support_arg = "Support argument: to be reasoned by LLM."
    else:
        instruction = f"Review why v{v} failed. Debate fix for v{v+1}."
        log(f"{loop_info} Static: {instruction}", agent_name)
        support_arg = "Support argument: to be reasoned by LLM."

    return {"static_argument": support_arg}

# ==========================================
# Phase 2: The Exchange (Synchronization)
# ==========================================
def exchange_arguments(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    log(f"{loop_info} Exchanging arguments for rebuttal generation...", agent_name)
    return {}

# ==========================================
# Phase 3: Parallel Rebuttal Generation
# ==========================================
def generate_dynamic_rebuttal(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)    
    log(f"{loop_info} Dynamic: Writing rebuttal...", agent_name)
    rebuttal = "Dynamic Rebuttal."
    return {"dynamic_rebuttal": rebuttal}

def generate_static_rebuttal(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    log(f"{loop_info} Static: Writing rebuttal...", agent_name)
    rebuttal = "Static Rebuttal."
    return {"static_rebuttal": rebuttal}