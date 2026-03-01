import logging
from src.core.state import SpadeState, get_loop_info

logger = logging.getLogger(__name__)

# ==========================================
# Phase 1: Parallel Argument Generation
# ==========================================
def generate_dynamic_arg(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    
    # Inject the dynamic instruction
    if v == 1:
        instruction = "Select the winning patch from v1_patch_candidates for the closest to the real patch."
        logger.info(f"[Debater Agent:Dynamic] {loop_info} {instruction}")
        support_arg = "Support argument: to be reasoned by LLM."
    else:
        logger.info(f"[Debater Agent:Dynamic] {loop_info} Review why v{v} failed. Debate fix for v{v+1}.")
        support_arg = f"Dynamic Debater: to be reasoned by LLM."

    return {"dynamic_argument": support_arg}


def generate_static_arg(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    v = state.get("current_patch_version", 1)
    
    if v == 1:
        instruction = "Select the winning patch from v1_patch_candidates for the closest to the real patch."
        logger.info(f"[Debater Agent:Static] {loop_info} {instruction}")
        support_arg = "Support argument: to be reasoned by LLM."
    else:
        instruction = f"Review why v{v} failed. Debate fix for v{v+1}."
        logger.info(f"[Debater Agent:Static] {loop_info} {instruction}")
        support_arg = "Support argument: to be reasoned by LLM."

    return {"static_argument": support_arg}

# ==========================================
# Phase 2: The Exchange (Synchronization)
# ==========================================
def exchange_arguments(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    logger.info(f"[Debater Agents] {loop_info} Exchanging arguments for rebuttal generation...")
    return {}

# ==========================================
# Phase 3: Parallel Rebuttal Generation
# ==========================================
def generate_dynamic_rebuttal(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    logger.info(f"[Debater Agent:Dynamic] {loop_info} Writing rebuttal...")
    rebuttal = "Dynamic Rebuttal."
    return {"dynamic_rebuttal": rebuttal}

def generate_static_rebuttal(state: SpadeState):
    loop_info = get_loop_info(state, include_inner=True)
    logger.info(f"[Debater Agent:Static] {loop_info} Writing rebuttal...")
    rebuttal = "Static Rebuttal."
    return {"static_rebuttal": rebuttal}