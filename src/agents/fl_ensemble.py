import os
import json
import logging
from src.utils.logger import log
from src.core.state import BugContext, EditLocation, SpadeState
from src.utils.snippet_extractor import extract_snippet, extract_snippet_fix
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
            "resolution_status": ["fl_failed"]
        }

    suspicious_files, related_functions, edit_locations = fl_data

    # Inject fl data into context
    bug_context.suspicious_files = suspicious_files
    bug_context.related_functions = related_functions
    bug_context.edit_locations = edit_locations

    # Extract code snippets for each edit location
    suspicious_locs = {}
    for file in suspicious_files:
        suspicious_locs[file] = {}
        for func in related_functions.get(file, []):
            suspicious_locs[file][func] = []

    for edit_loc in edit_locations:
        file = edit_loc.file
        func = edit_loc.function
        suspicious_locs[file][func].extend(edit_loc.lines)
    
    print(">>> suspicious_loc:", suspicious_locs)

    too_long_files = []
    MAX_LINES = 500 # Threshold for too long snippets
    file_snippets = {}
    for file, funcloc in suspicious_locs.items(): #bug_context.suspicious_locs:
        # print(f">> Processing file: {file} with suspicious locations: {funcloc}")
        # if funcloc is not empty
        snippet = ""
        if funcloc:
            all_functions = [func for func in funcloc.keys()]
            all_lines = [line for lines in funcloc.values() for line in lines]
            snippet = extract_snippet_fix(
                        repo_path=bug_context.local_repo_path,
                        relative_file_path=file,
                        target_lines=all_lines,
                        function_names=all_functions, # combine main function and related functions for the extractor
                        margin=settings.SNIPPET_CONTEXT_LINES
                    )
        else:
            # then get the whole file as snippet
            snippet = extract_snippet_fix(
                repo_path=bug_context.local_repo_path,
                relative_file_path=file,
                margin=settings.SNIPPET_CONTEXT_LINES
            )
            # print(f">> Extracted snippet for {file}:\n{snippet}\n")
            if snippet.count('\n') >= MAX_LINES:
                too_long_files.append(file)
                continue
        
        file_snippets[file] = snippet

    #delete files with too long snippets from the context to avoid overwhelming the LLM
    if too_long_files:
        bug_context.suspicious_files = [f for f in bug_context.suspicious_files if f not in too_long_files]
        bug_context.related_functions = {k: v for k, v in bug_context.related_functions.items() if k not in too_long_files}
        bug_context.edit_locations = [loc for loc in bug_context.edit_locations if loc.file not in too_long_files]
        
        log(f"Removed {len(too_long_files)} files with snippets longer than {MAX_LINES} lines from the context to avoid overwhelming the LLM.", agent_name)
        log(f"Files removed: {', '.join(too_long_files)}", agent_name)
    bug_context.file_snippets = file_snippets

    # for file, snippet in file_snippets.items():
    #     log(f">>> 🔧 Snippet for {file}:\n{snippet}\n", agent_name)

    return {
        "bug_context": bug_context,
    }

def test_IO(bugContext):
    print("Suspicious Files:", bugContext.suspicious_files)
    print("Related Functions:", bugContext.related_functions)
    print("Edit Locations:")
    for loc in bugContext.edit_locations:
        print(f"- File: {loc.file}")
        print(f"  Function: {loc.function}")
        print(f"  Lines: {loc.lines}")
        print(f"  Related Functions: {loc.related_functions}")
        print(f"  Snippet:\n{loc.snippet}\n")

    print("Testing fisnished, exiting now.")
    
