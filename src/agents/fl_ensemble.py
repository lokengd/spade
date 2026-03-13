from src.utils.logger import log
from src.core.state import BugContext, EditLocation, SpadeState

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

    return {
        "bug_context": bug_context,
    }