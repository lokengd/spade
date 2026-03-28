import os
import logging
import re
from typing import Union, List, Tuple, Optional, Set, Dict
from src.utils.logger import log

caller = "SnippetExtractor2"

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
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    
    if idx >= len(lines):
        return None
        
    stripped = lines[idx].strip()
    if stripped.startswith('"""') or stripped.startswith("'''"):
        quote_char = stripped[:3]
        start_doc = idx
        if stripped.count(quote_char) >= 2 and len(stripped) >= 6:
            return start_doc, idx + 1
        idx += 1
        while idx < len(lines):
            if quote_char in lines[idx]:
                return start_doc, idx + 1
            idx += 1
    return None

def get_all_docstring_indices(lines: List[str]) -> Set[int]:
    """Detects all docstring line indices in the file."""
    doc_indices = set()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("def ", "class ")):
            d_range = get_docstring_range(lines, i)
            if d_range:
                for idx in range(d_range[0], d_range[1]):
                    doc_indices.add(idx)
    return doc_indices

def get_margin_range(idx: int, margin: int, total_lines: int, start_limit: int = 0, end_limit: int = None) -> Tuple[int, int]:
    """Computes range [left, right) with 'margin' lines on each side. Docstrings and comments are included in count."""
    if end_limit is None:
        end_limit = total_lines
    left = max(start_limit, idx - margin)
    right = min(end_limit, idx + margin + 1)
    return left, right

def find_function_end(lines: List[str], start_line: int) -> int:
    """Find the end line of a function starting at start_line using indentation."""
    if start_line >= len(lines):
        return start_line
    
    func_line = lines[start_line]
    func_indent = len(func_line) - len(func_line.lstrip())
    
    end_line = start_line
    for i in range(start_line + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            end_line = i
            continue
        
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= func_indent:
            if line.strip().startswith(("def ", "class ", "@")):
                break
            elif current_indent < func_indent:
                break
        end_line = i
    return end_line

def find_method_in_class(lines: List[str], class_name: str, method_name: str) -> Optional[Tuple[int, int]]:
    """Find a method within a class."""
    class_pattern = re.compile(rf"^\s*class\s+{re.escape(class_name)}\b")
    method_pattern = re.compile(rf"^\s*def\s+{re.escape(method_name)}\b")
    
    in_class = False
    class_indent = 0
    
    for i, line in enumerate(lines):
        if not in_class:
            if class_pattern.search(line):
                in_class = True
                class_indent = len(line) - len(line.lstrip())
        else:
            stripped = line.lstrip()
            if stripped and not stripped.startswith("#"):
                current_indent = len(line) - len(stripped)
                if current_indent <= class_indent and (line.strip().startswith("class ") or line.strip().startswith("def ")):
                    in_class = False
                    continue
            
            if method_pattern.search(line):
                return (i, find_function_end(lines, i))
    return None

def extract_single_file_snippet(repo_path: str, relative_file_path: str, target_lines: List[int] = None, function_names: List[str] = None, margin: int = 5, include_docstring: bool = False, include_imports: bool = False) -> str:
    """Extracts snippet from a single file. Line numbers and content are based on the original source file."""
    full_path = os.path.join(repo_path, relative_file_path)
    if not os.path.exists(full_path):
        return f"# [Error] Could not locate {relative_file_path} in local repository."

    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    if not lines:
        return f"# [Error] File {relative_file_path} is empty."

    docstring_indices = get_all_docstring_indices(lines) if not include_docstring else set()

    # 1. Extract imports
    imports = []
    if include_imports:
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("class ") or stripped.startswith("def "):
                break
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(f"   {i + 1:4d}: {line.rstrip()}")

    # 2. Identify code ranges
    ranges = []
    targets = set(target_lines or [])
    requested_func_starts = set()
    func_names = function_names or []

    if not func_names and not targets:
        ranges.append((0, min(len(lines), 30)))
    else:
        for fname in func_names:
            start_idx = None
            end_idx = None
            class_idx = None
            if "." in fname:
                parts = fname.split(".", 1)
                result = find_method_in_class(lines, parts[0], parts[1])
                if result:
                    start_idx, end_idx = result
                    class_pattern = re.compile(rf"^\s*class\s+{re.escape(parts[0])}\b")
                    for j in range(start_idx, -1, -1):
                        if class_pattern.search(lines[j]):
                            class_idx = j
                            break
            else:
                pattern = re.compile(rf"^\s*(async\s+)?def\s+{re.escape(fname)}\b")
                for i, line in enumerate(lines):
                    if pattern.match(line):
                        start_idx = i
                        end_idx = find_function_end(lines, i)
                        break
            
            if start_idx is not None and end_idx is not None:
                requested_func_starts.add(start_idx)
                if class_idx is not None:
                    requested_func_starts.add(class_idx)
                
                targets_in_func = [t for t in targets if start_idx < t <= end_idx]
                if not targets_in_func:
                    # Full extraction with some margin context
                    l, r = get_margin_range(start_idx, margin, len(lines), 0, len(lines))
                    ranges.append((l, r))
                    l, r = get_margin_range(end_idx, margin, len(lines), 0, len(lines))
                    ranges.append((l, r))
                    ranges.append((start_idx, end_idx + 1))
                    if class_idx is not None:
                        ranges.append((class_idx, class_idx + 1))
                else:
                    # Surgical Mode: include class/func headers and targets
                    ranges.append((start_idx, start_idx + 1))
                    if class_idx is not None:
                        ranges.append((class_idx, class_idx + 1))
                    for tl in targets_in_func:
                        l, r = get_margin_range(tl - 1, margin, len(lines), start_idx, end_idx + 1)
                        ranges.append((l, r))

        # Handle targets not in functions
        for tl in targets:
            if not any(start <= tl-1 < end for start, end in ranges):
                l, r = get_margin_range(tl - 1, margin, len(lines))
                ranges.append((l, r))

    # 3. Merge ranges
    ranges.sort()
    merged = []
    if ranges:
        curr_start, curr_end = ranges[0]
        for next_start, next_end in ranges[1:]:
            if next_start <= curr_end + 2:
                curr_end = max(curr_end, next_end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged.append((curr_start, curr_end))

    # 4. Construct snippet
    result = [f"### File: {relative_file_path}", "```python"]
    if imports:
        result.append("# --- Imports ---")
        result.extend(imports)
        result.append("...")

    for i, (start, end) in enumerate(merged):
        if i > 0:
            result.append("    ...")
        
        last_was_skipped = False
        for idx in range(start, end):
            if idx in docstring_indices:
                if not last_was_skipped:
                    result.append("    ...")
                last_was_skipped = True
                continue
            
            last_was_skipped = False
            marker = ">> " if (idx + 1) in targets else "   "
            if idx in requested_func_starts and (idx + 1) not in targets:
                marker = "f> "
            result.append(f"{marker}{idx + 1:4d}: {lines[idx].rstrip()}")

    result.append("```")
    return "\n".join(result)

def extract_snippet(repo_path: str, suspicious_files: List[str], related_functions: Dict[str, List[str]], edit_locations: Dict[str, Dict], margin: int = 5, include_docstring: bool = False, include_imports: bool = False) -> str:
    """
    Extracts snippets from all suspicious files, related functions, and edit locations.
    """
    all_files = set(suspicious_files)
    all_files.update(related_functions.keys())
    all_files.update(edit_locations.keys())
    
    snippets = []
    for rel_path in sorted(all_files):
        target_lines = []
        if rel_path in edit_locations:
            loc = edit_locations[rel_path]
            if "lines" in loc:
                target_lines = loc["lines"]
        
        function_names = []
        if rel_path in related_functions:
            function_names.extend(related_functions[rel_path])
        if rel_path in edit_locations:
            loc = edit_locations[rel_path]
            if "function" in loc and loc["function"]:
                if loc["function"] not in function_names:
                    function_names.append(loc["function"])
        
        file_snippet = extract_single_file_snippet(
            repo_path=repo_path,
            relative_file_path=rel_path,
            target_lines=target_lines,
            function_names=function_names,
            margin=margin,
            include_docstring=include_docstring,
            include_imports=include_imports
        )
        snippets.append(file_snippet)
    
    return "\n\n".join(snippets)
