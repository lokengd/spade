import logging
import uuid
from langgraph.checkpoint.sqlite import SqliteSaver
from src.core.graph import build_graph, draw_graph
from src.core.state import BugContext
from src.core.dataset_loader import DatasetLoader
from src.evaluation import cleanup_evaluation_dir, setup_evaluation_environment
from src.utils.logger import log, setup_logger, get_log_header, get_memory_state
from config import settings

def run_spade(task: dict):

    # Assign unique thread id for the bug_id (support multiple runs and used in logging and checkpointing)
    bug_id = task["instance_id"]
    thread_suffix = uuid.uuid4().hex[:6] 
    thread_id = f"{bug_id}_{thread_suffix}"        
        
    # Setup the logger
    setup_logger(thread_id)
    log(get_log_header(thread_id))

    # Setup SQLite memory database
    db_path = settings.DATA_DIR / "checkpoints.sqlite"

    with SqliteSaver.from_conn_string(str(db_path)) as memory:
        
        graph = build_graph() 
        app = graph.compile(checkpointer=memory)
        #draw_graph(app)

        config = {"configurable": {"thread_id": thread_id}}
        state_snapshot = app.get_state(config)
        
        if not state_snapshot.values:
            # No memory found
            log(f"NEW run for {bug_id}. Loading dataset...")
            
            loader = DatasetLoader()
            test_data = loader.load_data()
            # filter the dataset to find that exact bug_id
            task = next(item for item in test_data if item["instance_id"] == bug_id)

            repo_path = loader.load_repo(task)
            
            initial_state = {
                "thread_id": thread_id,  
                "bug_context": BugContext(
                    bug_id=task["instance_id"],
                    issue_text=task["problem_statement"],
                    local_repo_path=str(repo_path),
                    base_commit=task["base_commit"],
                    suspicious_files=[], # to be populated by FL Ensemble Agent
                    fail_to_pass=task["FAIL_TO_PASS"],
                    pass_to_pass=task["PASS_TO_PASS"]
                ),        
            }

            for event in app.stream(initial_state, config=config):
                for node_name, state_update in event.items():
                    pass
                    #log(f"Finished node: {node_name}")
            
        else:
            # Memory found
            log(f"Memory found! Resuming run for {bug_id} from exact last step...")
            
            # Pass None (state) as the state, but still use streams
            for event in app.stream(None, config=config):
                for node_name, state_update in event.items():
                    pass
                    #log(f"Finished node: {node_name}")

        memory_state = app.get_state(config).values
        log(get_memory_state(memory_state))

if __name__ == "__main__":

    # Reset any stale evaluation artifacts from previous runs, then initialize SWE-bench Lite evaluation environment
    log("Setting up evaluation environment...", "Main", level=logging.INFO)
    cleanup_evaluation_dir()

    if not setup_evaluation_environment():
        log("Failed to set up evaluation environment. Check logs for details.", "Main", level=logging.CRITICAL)
        raise RuntimeError("Failed to set up evaluation environment.")

    log("Evaluation environment setup complete. Starting SPADE runs...", "Main", level=logging.INFO)

    # Initialize dataset Loader
    loader = DatasetLoader()
    test_data = loader.load_data()
    print(f"\nDataset Loaded. Found {len(test_data)} task instances.")

    # ---- DEMO PURPOSE: Just run the first test instance for now ----
    # Filter for a specific bug for sample evaluation run 
    test_data = [t for t in test_data if t['instance_id'] == "astropy__astropy-12907"]
    print("Available fields in a task:")
    for key in test_data[0].keys():
        print(f"- {key}")
    # ---- DEMO PURPOSE: End. ----

    for task in test_data:
        bug_id = task.get('instance_id', 'unknown_bug')
        try:
            run_spade(task) 
        except Exception as e:
            logging.error(f"FATAL: Evaluation failed for {bug_id}. Error: {e}")
            continue
