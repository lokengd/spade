from src.utils.logger import log
from src.core.state import BugContext, EditLocation, SpadeState
from src.utils.snippet_extractor import extract_snippet
from src.utils.db_logger import db_logger

agent_name = "FL_Ensemble"

def run(state: SpadeState):
    log("Running analysis...", agent_name)
    # Get existing BugContext from state
    bug_context: BugContext = state["bug_context"]

    # Extract code snippets for each edit location
    for loc in bug_context.edit_locations:
        # Store the extracted snippet back in the edit location 
        if not loc.snippet:
            log(f"Extracting snippet for {loc.file} at {loc.function or 'lines ' + str(loc.lines)}", agent_name)
            loc.snippet = extract_snippet(
                repo_path=bug_context.local_repo_path,
                relative_file_path=loc.file,
                target_lines=loc.lines,
                function_name=loc.function,
                window_size=15
            )

    return {
        "bug_context": bug_context,
    }
