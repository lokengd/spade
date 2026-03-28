"""
Read `gold_patch_results/` and filter out gold patches where the number of lines changed (added + deleted) is less than a specified threshold.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
GOLD_PATCH_RESULTS_DIR = ROOT / "gold_patch_results"

LINE_CHANGE_THRESHOLD = 3  # Set the threshold for what counts as a "simple fix"
FILE_CHANGE_THRESHOLD = 1  # Optional: Set a threshold for the number of files changed in the patch
OUTPUT_FILE = GOLD_PATCH_RESULTS_DIR / f"instances_with_simple_fixes.txt"


if __name__ == "__main__":
    simple_fix_issues = []
    counter = 0

    print(f"Scanning gold patch results in {GOLD_PATCH_RESULTS_DIR} for issues with simple fixes...")
    print(f"Using line change threshold of {LINE_CHANGE_THRESHOLD} and file change threshold of {FILE_CHANGE_THRESHOLD}.")
    print(f"Length of gold patch results directory: {len(list(GOLD_PATCH_RESULTS_DIR.iterdir()))} entries.")

    for issue_dir in GOLD_PATCH_RESULTS_DIR.iterdir():
        if issue_dir.is_dir():
            patch_info_file = issue_dir / "patch.diff"
            if patch_info_file.exists():
                counter += 1
                print(f"Processing instance {counter}: {issue_dir.name}")
                with open(patch_info_file, "r") as f:
                    patch_diff = f.read()

                # Count the number of lines added and deleted in the patch
                changed_files = sum(1 for line in patch_diff.splitlines() if line.startswith("diff --git"))
                added_lines = sum(1 for line in patch_diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
                deleted_lines = sum(1 for line in patch_diff.splitlines() if line.startswith("-") and not line.startswith("---"))
                total_line_changes = added_lines + deleted_lines

                if total_line_changes <= LINE_CHANGE_THRESHOLD and changed_files <= FILE_CHANGE_THRESHOLD:
                    simple_fix_issues.append(issue_dir.name)

    simple_fix_issues.sort()
    with open(OUTPUT_FILE, "w") as f:
        for issue in simple_fix_issues:
            f.write(f"{issue}\n")

    print(f"Identified {len(simple_fix_issues)} issues with simple fixes. Results saved to {OUTPUT_FILE}.")
