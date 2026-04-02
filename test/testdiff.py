from difflib import unified_diff

def generate_diff(filepath: str, original: str, modified: str) -> str:
    """Generate unified diff."""
    return "\n".join(unified_diff(
        original.split("\n"), modified.split("\n"),
        fromfile=f"a/{filepath}", tofile=f"b/{filepath}", lineterm=""
    ))

def generate_diff_all(file_contents: dict, new_contents: dict) -> dict:
    """Generate unified diffs for all edited files."""
    diffs = {}
    for filepath, new_content in new_contents.items():
        original_content = file_contents.get(filepath, "")
        diff = generate_diff(filepath, original_content, new_content)
        if diff:
            git_header = f"diff --git a/{filepath} b/{filepath}\n"
            diffs[filepath] = git_header + diff

    return diffs

if __name__ == "__main__":
    # Example usage
    # for file example.py
    original = """def add(a, b):
    return a + b
"""
    modified = """def add(a, b):
    return a + b
"""
    # for file new_file.py
    original_new = """new"""
    modified_new = """new"""
    #create file_contents dict for testing
    file_contents = {"example.py": original, "new_file.py": original_new}
    new_contents = {"example.py": modified, "new_file.py": modified_new}


    diffs = generate_diff_all(file_contents, new_contents)

    all_patches = [diff for diff in diffs.values() if diff.strip()]
    
    # Combine all patches
    final_patch = "\n\n".join(all_patches)

    print(final_patch)