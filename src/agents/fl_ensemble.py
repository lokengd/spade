import os
import json
import logging
from src.utils.logger import log
from src.core.state import BugContext, EditLocation, SpadeState
from src.utils.snippet_extractor import extract_snippet
from src.utils.db_logger import db_logger
from src.core import settings

agent_name = "FL_Ensemble"

def load_fl_data(bug_id: str):
    """Loads Fault Localization data from the results JSONL file defined in settings.FL_RESULTSET."""
    fl_file = settings.FL_RESULTSET
    if not os.path.exists(fl_file):
        log(f"Warning: FL results file {fl_file} not found.", agent_name, level=logging.WARNING)
        return None
    
    with open(fl_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("instance_id") == bug_id:
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
                                try:
                                    lines.append(int(part.replace('line: ', '').strip()))
                                except ValueError:
                                    continue
                        
                        edit_locations.append(EditLocation(
                            file=file,
                            function=function_name,
                            lines=lines if lines else None,
                            related_functions=related_functions.get(file, [])
                        ))
                
                return suspicious_files, related_functions, edit_locations
    return None

def run(state: SpadeState):
    log("Running analysis...", agent_name)
    
    bug_context: BugContext = state["bug_context"]
    
    # FL data: Load pre-calculated FL data from result file
    log(f"Loading FL data for {bug_context.bug_id} from {settings.FL_RESULTSET}...", agent_name)
    fl_data = load_fl_data(bug_context.bug_id)
    
    if fl_data is None:
        log(f"Error: No FL data found for {bug_context.bug_id} in fl resultset.", agent_name, level=logging.ERROR)
        return {
            "resolution_status": "fl_failed"
        }

    suspicious_files, related_functions, edit_locations = fl_data

    # Inject fl data into context
    bug_context.suspicious_files = suspicious_files
    bug_context.related_functions = related_functions
    bug_context.edit_locations = edit_locations

    # Extract code snippets for each edit location
    for loc in bug_context.edit_locations:
        # Store the extracted snippet back in the edit location 
        if not loc.snippet:
            loc.snippet = extract_snippet(
                repo_path=bug_context.local_repo_path,
                relative_file_path=loc.file,
                target_lines=loc.lines,
                function_names=loc.get_all_functions(), # combine main function and related functions for the extractor
                margin=settings.SNIPPET_CONTEXT_LINES
            )

    return {
        "bug_context": bug_context,
    }
