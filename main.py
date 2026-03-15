import logging
import uuid
import os
import json
from langgraph.checkpoint.sqlite import SqliteSaver
from src.core.graph import build_graph, draw_graph
from src.core.state import BugContext, EditLocation
from src.core.dataset_loader import DatasetLoader
from src.utils.logger import log, setup_logger, get_log_header, get_memory_state
from src.utils.db_logger import db_logger
from config import settings

def load_fl_data(bug_id: str):
    """Loads Fault Localization data from the sample results JSONL file."""
    fl_file = "results/afl-qwen2.5_32b_sample.jsonl"
    if not os.path.exists(fl_file):
        log(f"Warning: FL results file {fl_file} not found.", level=logging.WARNING)
        return [], {}, []
    
    with open(fl_file, "r") as f:
        for line in f:
            data = json.loads(line)
            if data["instance_id"] == bug_id:
                suspicious_files = data.get("found_files", [])
                
                # Parse related functions
                raw_related = data.get("found_related_locs", {})
                related_functions = {}
                for file, locs in raw_related.items():
                    funcs = []
                    for loc in locs:
                        if not loc: continue
                        for part in loc.split('\n'):
                            if part.startswith('function: '):
                                funcs.append(part.replace('function: ', '').strip())
                    related_functions[file] = funcs
                
                # Parse edit locations from found_edit_locs
                raw_edits = data.get("found_edit_locs", {})
                edit_locations = []
                for file, locs in raw_edits.items():
                    for loc in locs:
                        if not loc: continue
                        lines = []
                        function_name = None
                        for part in loc.split('\n'):
                            if part.startswith('function: '):
                                function_name = part.replace('function: ', '').strip()
                            elif part.startswith('line: '):
                                lines.append(int(part.replace('line: ', '').strip()))
                        
                        edit_locations.append(EditLocation(
                            file=file,
                            function=function_name,
                            lines=lines if lines else None
                        ))
                
                return suspicious_files, related_functions, edit_locations
    return [], {}, []

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
            
            # Load pre-calculated FL data from sample file
            suspicious_files, related_functions, edit_locations = load_fl_data(bug_id)

            initial_state = {
                "thread_id": thread_id,  
                "experiment_id": experiment_id,
                "bug_context": BugContext(
                    bug_id=task["instance_id"],
                    issue_text=task["problem_statement"],
                    local_repo_path=str(repo_path),
                    base_commit=task["base_commit"],
                    resolution_status="open",
                    suspicious_files=suspicious_files,
                    related_functions=related_functions,
                    edit_locations=edit_locations
                ),        
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

    # Initialize dataset Loader
    loader = DatasetLoader()
    test_data = loader.load_data()
    print(f"\nDataset Loaded. Found {len(test_data)} task instances.")

    # ---- DEMO PURPOSE: Run specific sample bugs ----
    # These should match instance_ids in results/afl-qwen2.5_32b_sample.jsonl
    demo_bugs = ["astropy__astropy-12907", "django__django-10914"]
    test_data = [t for t in test_data if t['instance_id'] in demo_bugs]
    # ---- DEMO PURPOSE: End. ----

    # Experiment Configuration
    thread_prefix = uuid.uuid4().hex[:6] 
    experiment_id = f"spade_baseline_demo_{thread_prefix}"
    experiment_desc = "Demo run of SPADE with sample bugs"
    db_logger.start_experiment(experiment_id, experiment_desc)
        
    for task in test_data:
        bug_id = task.get('instance_id', 'unknown_bug')
        thread_id = f"{thread_prefix}_{bug_id}"        
        
        setup_logger(thread_id)
        log(get_log_header(thread_id))

        try:
            run_spade(task, config={"configurable": {"thread_id": thread_id}}, experiment_id=experiment_id) 
        except Exception as e:
            log(f"FATAL: Evaluation failed for {bug_id}. Error: {e}", caller="Main", level=logging.ERROR)
            continue

    # Update final aggregated experiment metrics
    metrics = db_logger.get_experiment_metrics(experiment_id)
    db_logger.update_experiment_metrics(experiment_id, metrics)
    log(f"Experiment {experiment_id} finished. Metrics updated in database.", caller="Main")
