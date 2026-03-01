import logging
from src.core.graph import build_spade_orchestrator, draw_graph
from src.core.state import BugContext
from src.core.dataset_loader import DatasetLoader

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

if __name__ == "__main__":
    
    app = build_spade_orchestrator()
    #draw_graph(app)

    
    loader = DatasetLoader() # Load SWE-Bench-Lite dataset
    test_data = loader.load_lite_data()
    # Example: Get the first task instance
    task = test_data[0]

    # Setup the local files for the agents to read
    repo_path = loader.setup_task_env(task)

    initial_state = {
        "bug_id": task["instance_id"],  
        "bug_report": task["problem_statement"], # The GitHub issue text        
        # Bug Context for Agents
        "bug_context": BugContext(
            bug_id=task["instance_id"],
            issue_text=task["problem_statement"],
            local_repo_path=str(repo_path),
            base_commit=task["base_commit"],
            suspicious_files=[] # To be populated by FL Ensemble Agent
        ),        
    }

    config = {"configurable": {"thread_id": initial_state["bug_id"]}}

    print("\n" + "*"*40)
    print("-"*40)
    print(f"Starting SPADE Run: {initial_state['bug_id']}")
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

