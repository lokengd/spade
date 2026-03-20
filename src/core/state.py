from typing import Dict, TypedDict, List, Optional, Annotated
from pydantic import BaseModel
import operator
from typing_extensions import NotRequired

P_UNCONSTRAINED = "P_unconstrained" # Unconstrained pattern identifier

# Pydantic Models (Strictly Typed Artifacts)
class EditLocation(BaseModel):
    file: str
    function: Optional[str] = None
    lines: Optional[List[int]] = None
    related_functions: List[Optional[str]] = None
    snippet: Optional[str] = None
    
    def get_all_functions(self) -> List[str]:
        """Returns a combined, deduplicated list of all associated functions."""
        all_funcs = []
        
        # Add the primary function if it exists
        if self.function: 
            all_funcs.append(self.function)
            
        # Add related functions, filtering out Nones and duplicates
        if self.related_functions:
            for rf in self.related_functions:
                if rf and rf not in all_funcs:
                    all_funcs.append(rf)
        
        return all_funcs

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
    strategy: str # K+1 patterns: p1, p2, p1+p2, + 1 Unconstrained: pX
    version: int = 1 # Version number (1 for v1, 2 for v2, etc.)
    origin_v1_id: Optional[str] = None # Link back to the original v1 candidate
    status: str = "pending" # pending, passed, failed
    execution_trace: Optional[str] = None

def add_metrics(old_data: dict, new_data: dict) -> dict:
    """Reducer function to safely add token and cost metrics together."""
    if not old_data: old_data = {}
    if not new_data: new_data = {}
    return {k: old_data.get(k, 0) + new_data.get(k, 0) for k in set(old_data) | set(new_data)}

class SpadeState(TypedDict):
    thread_id: str # Unique identifier for the execution thread, tied to the bug_context 
    experiment_id: str # Identifier for the current experiment
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
    resolution_status: str # 'resolved', 'open', different scenario of 'failed': e.g. v1_failed, reproduction_failed, patchgen_failed pattern_selection_failed etc

    # Telemetry
    total_metrics: Annotated[dict, add_metrics]

    # Evaluation of no and current patch candidate - populated after evaluation step
    reproduction_evaluation_result: NotRequired[EvaluationResult] # Populated after reproduction step
    v1_patches_evaluation_result: NotRequired[List[EvaluationResult]] # Populated after running on proposed patch
    refined_patch_evaluation_result: NotRequired[EvaluationResult] # Populated after running on proposed patch
