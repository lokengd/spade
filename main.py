import logging
import uuid
from venv import logger
from langgraph.checkpoint.sqlite import SqliteSaver
from src.core.graph import build_graph, draw_graph
from src.core.state import BugContext
from src.core.dataset_loader import DatasetLoader
from src.utils.logger import setup_logger 
from config import settings

def print_run_start_banner(bug_id: str):
    print("\n" + "*"*40)
    print(f"Starting SPADE Run: {bug_id}")
    print("*"*40)

def print_memory_state(shared_memory_state: dict):
    print("\n" + "="*40)
    print("SHARED MEMORY STATE")
    print("-"*40)
    for key, value in shared_memory_state.items():
        print(f"{key}: {value}")

    print("="*40)

def run_spade(bug_id: str):
    # Setup SQLite memory database
    db_path = settings.DATA_DIR / "checkpoints.sqlite"

    with SqliteSaver.from_conn_string(str(db_path)) as memory:
        
        graph = build_graph() 
        app = graph.compile(checkpointer=memory)
        #draw_graph(app)

        # The checkpointer permanently ties the SpadeState to the thread_id (bug_id).
        run_suffix = uuid.uuid4().hex[:6] 
        unique_thread_id = f"{bug_id}-{run_suffix}"        
        config = {"configurable": {"thread_id": unique_thread_id}}
        
        # Setup the logger
        log_file_path = setup_logger(unique_thread_id)
        logger = logging.getLogger(__name__) 
        logger.info(f"Start thread run: {log_file_path}")

        state_snapshot = app.get_state(config)
        
        if not state_snapshot.values:
            # No memory found
            logger.info(f"NEW run for {bug_id}. Loading dataset...")
            
            loader = DatasetLoader()
            test_data = loader.load_data()
            # filter the dataset to find that exact bug_id
            task = next(item for item in test_data if item["instance_id"] == bug_id)

            repo_path = loader.load_repo(task)
            
            initial_state = {
                "thread_id": unique_thread_id,  
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
                        
            print_run_start_banner(bug_id)

            for event in app.stream(initial_state, config=config):
                for node_name, state_update in event.items():
                    pass
                    #logger.info(f"Finished node: {node_name}")
            
        else:
            # Memory found
            logger.info(f"Memory found! Resuming run for {bug_id} from exact last step...")
            
            print_run_start_banner(bug_id)

            # Pass None (state) as the state, but still use streams
            for event in app.stream(None, config=config):
                for node_name, state_update in event.items():
                    pass
                    #logger.info(f"Finished node: {node_name}")

        shared_memory_state = app.get_state(config).values
        print_memory_state(shared_memory_state)


if __name__ == "__main__":
    
    loader = DatasetLoader()
    test_data = loader.load_data()
    task = test_data[0] # Grab the first task (test_data[0]) for test run
    # Inspect test data
    print("\nAvailable fields in Dataset")
    for key in task.keys():
        print(f"- {key}")

    bug_id = task["instance_id"]
    run_spade(bug_id)

