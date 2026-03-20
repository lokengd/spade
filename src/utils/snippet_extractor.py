import os
import logging
import re
from typing import Union, List, Tuple, Optional, Set
from src.utils.logger import log

caller = "SnippetExtractor"

def get_function_body_range(lines: List[str], start_idx: int) -> Tuple[int, int]:
    """Finds the end of a function body based on indentation."""
    line = lines[start_idx]
    indent_match = re.match(r"^(\s*)", line)
    indent = len(indent_match.group(1)) if indent_match else 0
    
    end_idx = start_idx + 1
    while end_idx < len(lines):
        curr_line = lines[end_idx]
        if curr_line.strip():
            curr_indent_match = re.match(r"^(\s*)", curr_line)
            curr_indent = len(curr_indent_match.group(1)) if curr_indent_match else 0
            if curr_indent <= indent and (curr_line.lstrip().startswith("def ") or curr_line.lstrip().startswith("class ")):
                return start_idx, end_idx
        end_idx += 1
    return start_idx, len(lines)

def get_docstring_range(lines: List[str], func_idx: int) -> Optional[Tuple[int, int]]:
    """Finds the range of the docstring for a function/class."""
    idx = func_idx + 1
    # Skip decorators or empty lines immediately following def
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    
    if idx >= len(lines):
        return None
        
    stripped = lines[idx].strip()
    if stripped.startswith('"""') or stripped.startswith("'''"):
        quote_char = stripped[:3]
        start_doc = idx
        # Single line docstring
        if stripped.count(quote_char) >= 2 and len(stripped) >= 6:
            return start_doc, idx + 1
        # Multi line docstring
        idx += 1
        while idx < len(lines):
            if quote_char in lines[idx]:
                return start_doc, idx + 1
            idx += 1
    return None

def extract_snippet(repo_path: str, relative_file_path: str, target_lines: List[int] = None, function_names: Union[str, List[str]] = None, margin: int = 5, include_docstring: bool = False) -> str:
    """
    Extracts the import statements and the full code of requested functions, 
    plus a window around target lines. Docstrings are excluded by default.
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

    # 1. Extract imports
    imports = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("class ") or stripped.startswith("def "):
            break
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(f"   {i + 1:4d}: {line.rstrip()}")

    # 2. Identify code ranges to include
    ranges = [] # list of (start_idx, end_idx)
    targets = set(target_lines or [])
    
    # Always include windows around target lines
    for tl in targets:
        ranges.append((max(0, tl - 1 - margin), min(len(lines), tl + margin)))

    # Handle requested functions
    func_names = [function_names] if isinstance(function_names, str) else (function_names or [])
    requested_func_starts = set()
    for fname in func_names:
        pattern = re.compile(rf"^\s*(async\s+)?def\s+{re.escape(fname)}\b")
        for i, line in enumerate(lines):
            if pattern.match(line):
                requested_func_starts.add(i)
                start, end = get_function_body_range(lines, i)
                
                # Check if any target lines fall within this function's body
                targets_in_func = [t for t in targets if start < t <= end]
                
                if not targets_in_func:
                    # Function was requested but no specific lines targeted in it: show full code
                    ranges.append((start, end))
                else:
                    # Function contains targets: ensure header is included. 
                    # The windows around targets are already added above.
                    ranges.append((i, i + 1))
                break

    if not ranges:
        # Fallback: top of file
        ranges.append((0, min(len(lines), 30)))

    # 3. Merge overlapping or adjacent ranges
    ranges.sort()
    merged = []
    if ranges:
        curr_start, curr_end = ranges[0]
        for next_start, next_end in ranges[1:]:
            if next_start <= curr_end + 2: # Merge if separated by only 2 lines
                curr_end = max(curr_end, next_end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged.append((curr_start, curr_end))

    # 4. Identify docstrings to skip
    docstring_indices: Set[int] = set()
    if not include_docstring:
        for i, line in enumerate(lines):
            # Only detect docstrings for definitions within our included ranges
            if any(start <= i < end for start, end in merged):
                if line.lstrip().startswith(("def ", "class ")):
                    d_range = get_docstring_range(lines, i)
                    if d_range:
                        for d_idx in range(d_range[0], d_range[1]):
                            # Never skip a line if it's explicitly targeted
                            if (d_idx + 1) not in targets:
                                docstring_indices.add(d_idx)

    # 5. Construct snippet
    result = ["```python"] 
    if imports:
        result.append("# --- Imports ---")
        result.extend(imports)
        result.append("...")

    for i, (start, end) in enumerate(merged):
        if i > 0:
            result.append("    ...") # Gap between ranges
        
        last_was_skipped = False
        for idx in range(start, end):
            if idx in docstring_indices:
                if not last_was_skipped:
                    result.append("    ...") # Jump over docstring
                last_was_skipped = True
                continue
            
            last_was_skipped = False
            marker = ">> " if (idx + 1) in targets else "   "
            # Mark function starts if they were requested
            if idx in requested_func_starts and (idx + 1) not in targets:
                marker = "f> "
            result.append(f"{marker}{idx + 1:4d}: {lines[idx].rstrip()}")

    result.append("```")
    return "\n".join(result)
