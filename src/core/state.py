from typing import Dict, TypedDict, List, Optional, Annotated
from pydantic import BaseModel
import operator

# Pydantic Models (Strictly Typed Artifacts)
class EditLocation(BaseModel):
    file: str
    function: Optional[str] = None
    lines: Optional[List[int]] = None
    snippet: Optional[str] = None

class BugContext(BaseModel):
    bug_id: str
    issue_text: str
    local_repo_path: str
    base_commit: str

    # Expected output from FL Ensemble and Reproduction steps to inform pattern selection
    suspicious_files: List[str] = []
    related_functions: Dict[str, List[str]] = {}
    edit_locations: List[EditLocation] = []

    # Expected output from  Reproduction steps 
    error_trace: Optional[str] = None
    fail_to_pass: str = None
    pass_to_pass: str = None

class EvaluationResult(BaseModel):
    # These 2 fields capture any errors or unexpected issues during the evaluation process itself (e.g., timeouts, docker errors, etc.)
    evaluation_error_message: Optional[str] = None
    evaluation_ran_successfully: bool = False

    # These fields capture the actual results of the test execution for a given patch candidate
    bug_resolved: bool = None
    patch_applied_successfully: bool = None

    total_tests: int = -1
    pass_to_pass_success: bool = None
    fail_to_pass_success: bool = None

    pass_to_pass_failed_tests: List[str] = None
    fail_to_pass_failed_tests: List[str] = None

    pass_to_pass_successful_tests: List[str] = None
    fail_to_pass_successful_tests: List[str] = None

    test_output: str = None
    failed_test_traces: Optional[dict] = None # Mapping of failed test cases to their execution traces

class PatchCandidate(BaseModel):
    id: str
    code_diff: str
    strategy: str # K+1 patterns: p1, p2, p1+p2, + 1 unconstrained: pX
    version: int = 1 # Version number (1 for v1, 2 for v2, etc.)
    origin_v1_id: Optional[str] = None # Link back to the original v1 candidate
    status: str = "pending" # pending, passed, failed
    execution_trace: Optional[str] = None
    evaluation: EvaluationResult = None # Populated after evaluation step

def add_metrics(old_data: dict, new_data: dict) -> dict:
    """Reducer function to safely add token and cost metrics together."""
    if not old_data: old_data = {}
    if not new_data: new_data = {}
    return {k: old_data.get(k, 0) + new_data.get(k, 0) for k in set(old_data) | set(new_data)}

class SpadeState(TypedDict):
    thread_id: str # Unique identifier for the execution thread, tied to the bug_context 
    bug_context: BugContext

    selected_patterns: List[str]
    active_pattern: str 
    
    # This tells LangGraph: "When multiple agents return v1_patches, do NOT overwrite. Instead, use operator.add to append them."
    v1_patches: Annotated[List[PatchCandidate], operator.add]
    
    # Historical trace of refined patches (v2, v3, etc.)
    refined_patches: Annotated[List[PatchCandidate], operator.add]
    
    # The winner from the last v1 pool or the previous refinement loop
    current_v1_id: str
    
    # Historical trace logs for analysis and potential LLM feedback
    historical_verdicts: Annotated[List[str], operator.add]
    failed_traces: Annotated[List[str], operator.add]
    
    # Active Debate (Overwritten each inner loop)
    dynamic_argument: Optional[str]
    static_argument: Optional[str]
    dynamic_rebuttal: Optional[str]
    static_rebuttal: Optional[str]
    verdict: Optional[str]
    
    # Control Flow
    outer_loop_count: int
    inner_loop_count: int
    current_patch_version: int  
    resolution_status: str # 'resolved', 'open', 'failed'    

    # Telemetry
    total_metrics: Annotated[dict, add_metrics]

def get_loop_info(state: SpadeState, include_inner: bool = True):
    """
    Centralized helper to extract N, M, V values.
    """
    from config.settings import N_OUTER_LOOPS, M_INNER_LOOPS, V_PATIENCE
    
    n = state.get("outer_loop_count", 1)
    m = state.get("inner_loop_count", 1)
    v = state.get("current_patch_version", 1)
    
    if include_inner:
        info_str = f"[N={n}/{N_OUTER_LOOPS}] [M={m}/{M_INNER_LOOPS}] [V={v}/{V_PATIENCE}]"
    else:
        info_str = f"[N={n}/{N_OUTER_LOOPS}]"
    
    return info_str
