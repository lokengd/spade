import logging
from src.core.graph import build_spade_orchestrator, draw_graph
from src.core.state import BugContext

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

mock_bug_context = BugContext(
    issue_text="Dummy bug report...",
    suspicious_files=[],
    error_trace=None
)

if __name__ == "__main__":
    
    app = build_spade_orchestrator()

    # draw_graph(app)

    # ==========================================
    # 2. Initialize the strictly-typed Shared Memory State
    # ==========================================
    initial_state = {
        "bug_report_id": "Mock run-1",
        "bug_context": mock_bug_context,
        
        "active_pattern": "",
        "selected_patterns": [],
        "v1_patches": [],
        "v2_patch": None,
        
        "historical_verdicts": [], 
        "failed_traces": [], 

        # Debate Artifacts initialized to None
        "dynamic_argument": None,
        "static_argument": None,
        "dynamic_rebuttal": None,
        "static_rebuttal": None,
        "verdict": None,
        
        "outer_loop_count": 1,
        "inner_loop_count": 1,  
        "current_patch_version": 1,        
        "resolution_status": "in_progress" # Matches our updated state
    }

    config = {"configurable": {"thread_id": initial_state["bug_report_id"]}}

    print("\n" + "*"*40)
    print("-"*40)
    print(f"Starting SPADE Run: {initial_state['bug_report_id']}")
    print("-"*40)
    print("*"*40)
    
    # 3. Stream the graph execution
    for event in app.stream(initial_state, config=config):
        for node_name, state_update in event.items():
            pass
            # print(f"Finished graph node: {node_name}\n")
            
    # 4. Inspect final Shared Memory State
    shared_memory_state = app.get_state(config).values
    
    print("\n" + "="*40)
    print("SHARED MEMORY STATE")
    print("="*40)
    print(f"Status: {shared_memory_state.get('resolution_status')}")
    print(f"Outer Loop Iterations: {shared_memory_state.get('outer_loop_count')}")
    print("\n--- Debate Panel Summary ---")
    print(f"Dynamic Argument: {shared_memory_state.get('dynamic_argument')}")
    print(f"Static Argument:  {shared_memory_state.get('static_argument')}")
    print(f"Dynamic Rebuttal: {shared_memory_state.get('dynamic_rebuttal')}")
    print(f"Static Rebuttal:  {shared_memory_state.get('static_rebuttal')}")
    print(f"Judge Verdict:    {shared_memory_state.get('verdict')}")
    print("="*40)

