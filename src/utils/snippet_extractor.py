import os
import logging
from src.utils.logger import log

caller = "SnippetExtractor"

def extract_snippet(repo_path: str, relative_file_path: str, target_lines: list[int] = None, function_name: str = None, window_size: int = 15) -> str:
    """
    Extracts the import statements and a window of code around the target lines.
    
    Args:
        repo_path: Absolute path to the cloned repository.
        relative_file_path: Path to the file relative to the repo root.
        target_lines: List of line numbers identified as suspicious.
        function_name: Name of the function to extract if target lines are not provided.
        window_size: Number of lines to include above and below the target lines.
    """
    full_path = os.path.join(repo_path, relative_file_path)
    
    if not os.path.exists(full_path):
        log(f"File not found: {full_path}", caller=caller, level=logging.WARNING)
        return f"# [Error] Could not locate {relative_file_path} in local repository."

    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    if not lines:
        log(f"File found but empty: {full_path}", caller=caller, level=logging.WARNING)
        return f"# [Error] File {relative_file_path} is empty."

    # Extract imports, assuming imports are at the top of the file (before any class or function definitions)
    imports = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Stop looking for imports if we hit a class or def
        if stripped.startswith("class ") or stripped.startswith("def "):
            break
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(f"   {i + 1:4d}: {line.rstrip()}")

    # Determine Bounds 
    start_idx, end_idx = 0, min(len(lines), window_size * 2) # Default top-of-file
    if target_lines:
        # if target lines are provided, use them
        min_line = min(target_lines)
        max_line = max(target_lines)
        start_idx = max(0, min_line - 1 - window_size)
        end_idx = min(len(lines), max_line + window_size)
    elif function_name:
        # else, find the function in the file
        func_def = f"def {function_name}("
        for i, line in enumerate(lines):
            if func_def in line:
                start_idx = max(0, i - 5) # 5 lines (a margin) above the def
                end_idx = min(len(lines), i + window_size * 2) # Extract a chunk of window_size*2 lines starting from the function definition
                break

    # Extract snippet
    snippet = []
    for i in range(start_idx, end_idx):
        marker = ">> " if (i + 1) in target_lines else "   "
        snippet.append(f"{marker}{i + 1:4d}: {lines[i].rstrip()}")

    # Return code snippet, start the opening backticks
    result = ["```python"] 
    if imports:
        result.append("# --- Imports ---")
        result.extend(imports)
        result.append("...")

    result.append(f"# --- Code Snippet (Lines {start_idx + 1}-{end_idx}) ---")
    result.extend(snippet)
    # Add the closing backticks
    result.append("```")

    return "\n".join(result)