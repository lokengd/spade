import logging
import uuid
from langgraph.checkpoint.sqlite import SqliteSaver
from src.core.graph import build_graph, draw_graph
from src.core.state import BugContext
from src.core.dataset_loader import DatasetLoader
from src.evaluation import cleanup_evaluation_dir, setup_evaluation_environment
from src.utils.logger import log, setup_logger, get_log_header, get_memory_state
from src.utils.db_logger import db_logger
from src.core import settings

def run_spade(task: dict, config: dict, experiment_id: str):

    # Assign unique thread id for the bug_id (support multiple runs and used in logging and checkpointing)
    thread_id = config["configurable"]["thread_id"]
    bug_id = task["instance_id"]
   
    # Setup SQLite checkpoint database
    ckpt_path = settings.DATA_DIR / "checkpoints.sqlite"
    
    # Log the start of this specific repair run using thread_id as run_id
    db_logger.start_repair_run(experiment_id=experiment_id, bug_id=bug_id, run_id=thread_id)

    with SqliteSaver.from_conn_string(str(ckpt_path)) as memory:
        
        graph = build_graph() 
        app = graph.compile(checkpointer=memory)
        #draw_graph(app)

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
                "experiment_id": experiment_id,
                "bug_context": BugContext(
                    bug_id=task["instance_id"],
                    issue_text=task["problem_statement"],
                    local_repo_path=str(repo_path),
                    base_commit=task["base_commit"],
                    resolution_status="open"
                ),
                "outer_loop_count": 1,
                "inner_loop_count": 1,
                "current_patch_version": 1,
                "resolution_status": "open"
            }

            for event in app.stream(initial_state, config=config):
                for node_name, state_update in event.items():
                    pass
            
        else:
            # Memory found
            log(f"Memory found! Resuming run for {bug_id} from exact last step...")
            
            for event in app.stream(None, config=config):
                for node_name, state_update in event.items():
                    pass

        memory_state = app.get_state(config).values
        log(get_memory_state(memory_state))

if __name__ == "__main__":

    # Reset any stale evaluation artifacts from previous runs, then initialize SWE-bench Lite evaluation environment
    setup_logger("evaluation")
    log("Setting up Docker environment for evaluation...", "Main", level=logging.INFO)
    cleanup_evaluation_dir()

    if not setup_evaluation_environment():
        log("Failed to set up Docker environment for evaluation. Check logs for details.", "Main", level=logging.CRITICAL)
        raise RuntimeError("Failed to set up Docker environment.")

    log("Evaluation environment setup complete. Starting SPADE runs...", "Main", level=logging.INFO)

    # Initialize dataset Loader
    loader = DatasetLoader()
    all_test_data = loader.load_data()
    print(f"\nDataset Loaded. Found {len(all_test_data)} task instances.")

    for experiment_id in settings.ACTIVE_EXPERIMENTS:
        exp_config = settings.update_orchestration_settings(experiment_id)
        experiment_desc = exp_config.get("description", "No description provided")
        bug_list = exp_config.get("bug_list", [])

        print(f"\n--- Starting Experiment: {experiment_id} ---")
        print(f"Description: {experiment_desc}")

        # Filter dataset based on bug_list
        if bug_list == "all":
            test_data = all_test_data
        else:
            test_data = [t for t in all_test_data if t['instance_id'] in bug_list]
        
        print(f"Bugs to process: {len(test_data)}")

        # Experiment ID in DB includes a unique suffix for this run
        db_experiment_id = f"{experiment_id}_{uuid.uuid4().hex[:6]}"
        db_logger.start_experiment(db_experiment_id, experiment_desc)
            
        for task in test_data:
            bug_id = task.get('instance_id', 'unknown_bug')
            thread_id = f"{db_experiment_id}_{bug_id}"        
            
            setup_logger(thread_id)
            log(get_log_header(db_experiment_id))

            try:
                run_spade(task, config={"configurable": {"thread_id": thread_id}}, experiment_id=db_experiment_id) 
            except Exception as e:
                log(f"FATAL: Evaluation failed for {bug_id}. Error: {e}", caller="Main", level=logging.ERROR)
                continue

        # Update final aggregated experiment metrics
        db_logger.update_experiment_metrics(db_experiment_id)
        log(f"Experiment {db_experiment_id} finished. Metrics updated in database.", caller="Main")
