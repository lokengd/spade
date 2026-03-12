from src.utils.logger import log
import uuid
from src.core.state import SpadeState, get_loop_info

agent_name = "PatchGen"

def generate_v1_patch(state: SpadeState):
    pattern = state.get("active_pattern", "unconstrained")
    loop_info = get_loop_info(state, include_inner=False)
    log(f"{loop_info} Working on strategy -> {pattern}", agent_name)
    
    patch_id = f"v1_{uuid.uuid4().hex[:6]}"
            
    patch = {
        "id": patch_id, 
        "code_diff": None, # Will be replaced by LLM code generation
        "strategy": pattern,
        "status": "pending"
    }
    
    # LangGraph's operator.add in SpadeState will merge this into the v1_patches list
    return {"v1_patches": [patch]}

# Generate version 2 (or higher)
def generate_refined_patch(state: SpadeState):
    v = state.get("current_patch_version", 1)
    loop_info = get_loop_info(state, include_inner=True)

    v_next = v # Incremented version is handled at test_agent._handle_fallback

    # Retrieve the origin ID (the v1 patch we are building upon)
    # This should be set by the Judge or a selection node earlier in the loop
    origin_id = state.get("current_v1_id", "unknown_origin")

    log(f"{loop_info} Improve previous patch {origin_id} and generate new patch v{v_next}...", agent_name)

    patch_id = f"v{v_next}_{uuid.uuid4().hex[:6]}"

    patch = {
        "id": patch_id, 
        "code_diff": None, # Will be replaced by LLM code
        "strategy": f"refined_from_debate_v{v_next}",
        "status": "pending",
        "origin_v1_id": origin_id  # Link back to the original v1 candidate
    }

    # Return the new patch AND the incremented version to update the global state
    return {
        "current_refined_patch": patch,
        "current_patch_version": v_next 
    }
