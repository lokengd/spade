from src.utils.logger import log
from src.core.state import BugContext, EditLocation, SpadeState
from src.utils.snippet_extractor import extract_snippet

agent_name = "FL_Ensemble"

def run(state: SpadeState):
    log("Running analysis...", agent_name)
    # Get existing BugContext from state
    bug_context: BugContext = state["bug_context"]

    # Update only the FL results
    # ---- DEMO PURPOSE: sample bug context for testing - astropy__astropy-12907 ----
    bug_context.suspicious_files = [
        "astropy/modeling/separable.py",
        "astropy/modeling/core.py",
        "astropy/modeling/models.py",
        "astropy/modeling/utils.py"
    ]
    bug_context.related_functions = {
        "astropy/modeling/separable.py": [
            "separability_matrix",
            "_cstack",
            "_coord_matrix"
        ],
        "astropy/modeling/core.py": [
            "CompoundModel.evaluate",
            "CompoundModel.__init__"
        ]
    }
    bug_context.edit_locations = [
        EditLocation(
            file="astropy/modeling/separable.py",
            function="_coord_matrix",
            lines=[204, 210]
        )
    ]
    # ---- DEMO PURPOSE: End. ----


    # Extract code snippets for each edit location
    for loc in bug_context.edit_locations:
        # Store the extracted snippet back in the edit location for later use in the pipeline
        loc.snippet = extract_snippet(
            repo_path=bug_context.local_repo_path,
            relative_file_path=loc.file,
            target_lines=loc.lines,
            function_name=loc.function,
            window_size=20
        )

    return {
        "bug_context": bug_context,
    }