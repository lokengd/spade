#!/usr/bin/env python3
import os
from pathlib import Path
from src.core.dataset_loader import DatasetLoader

def main():
    # 1. Initialize dataset Loader and load data
    print("Loading SWE-bench-lite dataset...")
    loader = DatasetLoader()
    all_test_data = loader.load_data()
    print(f"Loaded {len(all_test_data)} task instances.")

    # 2. Define root directory for gold patches
    # Based on user request: fl_results/gold_patch/
    base_output_dir = Path("fl_results/gold_patch")
    base_output_dir.mkdir(parents=True, exist_ok=True)

    # 3. Process each task
    for task in all_test_data:
        instance_id = task.get("instance_id")
        patch = task.get("patch")
        
        if not instance_id or not patch:
            continue

        # Group by repository. instance_id format is usually 'repo__owner-id'
        # e.g., 'astropy__astropy-14995' -> repo is 'astropy__astropy'
        if "__" in instance_id:
            repo_name = instance_id.split("-")[0] # e.g. astropy__astropy
        else:
            # Fallback if format differs
            repo_name = instance_id.split("-")[0]

        # Create repository subfolder
        repo_dir = base_output_dir / repo_name
        repo_dir.mkdir(parents=True, exist_ok=True)

        # Save gold patch to file
        file_path = repo_dir / f"{instance_id}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(patch)
        
    print(f"Finished! Gold patches saved to {base_output_dir}")

if __name__ == "__main__":
    main()
