"""
Create subset files containing lists of instance IDs for different subsets of the data
"""

from pathlib import Path
import json
import os


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

INSTANCES_DATA_FILE = ROOT / "afl-qwen2.5_32b.jsonl"
INSTANCES_LIST_FILE = PROJECT_ROOT / "instances_with_simple_fixes.txt"

SAVING_FOLDER_NAME = "subset_files"
SAVING_FILE_NAME = "spade_baseline_k2_n3_m1_v2_subset_{subset_number}.jsonl"

NUMBER_OF_SUBSETS = 5


if __name__ == "__main__":
    print("Starting to create subset files...")
    if not INSTANCES_DATA_FILE.exists():
        print(f"Data file {INSTANCES_DATA_FILE} does not exist.")
        exit(1)

    if not INSTANCES_LIST_FILE.exists():
        print(f"Instances list file {INSTANCES_LIST_FILE} does not exist.")
        exit(1)

    print(f"Found data file at {INSTANCES_DATA_FILE} and instances list at {INSTANCES_LIST_FILE}. Proceeding with subset creation.")

    with open(INSTANCES_DATA_FILE, "r") as f:
        instances_data = f.readlines()
        instances_data = [json.loads(line) for line in instances_data]
        instances_data_dict = {instance["instance_id"]: instance for instance in instances_data}

    with open(INSTANCES_LIST_FILE, "r") as f:
        instance_ids = list(line.strip() for line in f.readlines())

    total_instances = len(instance_ids)
    print(f"Total Filtered Instances: {total_instances}")

    # All subsets cannot be same and hence split as equally as possible and keep assigning remaining instances to every subset until all instances are assigned
    # subset_size = total_instances // NUMBER_OF_SUBSETS
    # print(f"Subset size: {subset_size}")

    total_assigned = 0
    subsets = {i: [] for i in range(1, NUMBER_OF_SUBSETS + 1)}

    # Round-robin assignment of instances to subsets
    subset_index = 1
    while total_assigned < total_instances:
        print(f"Assigning instance {total_assigned + 1}/{total_instances} to subset {subset_index}...")

        subsets[subset_index].append(instance_ids[total_assigned])
        total_assigned += 1

        subset_index += 1
        if subset_index > NUMBER_OF_SUBSETS:
            subset_index = 1
    
    print("Finished assigning instances to subsets. Now writing to files...")

    os.makedirs(ROOT / SAVING_FOLDER_NAME, exist_ok=True)
    
    for subset_number, subset_instance_ids in subsets.items():
        print(f"Writing subset {subset_number} with {len(subset_instance_ids)} instances to file...")

        file_path = ROOT / SAVING_FOLDER_NAME / SAVING_FILE_NAME.format(subset_number=subset_number)

        total_written_instances = 0

        with open(file_path, "w", encoding="utf-8") as f:
            for instance_id in subset_instance_ids:
                if not instance_id in instances_data_dict:
                    print(f"Instance ID {instance_id} not found in instances data.")
                    continue

                f.write(json.dumps(instances_data_dict[instance_id], ensure_ascii=False) + "\n")
                total_written_instances += 1
        
        print(f"Wrote {total_written_instances} instance IDs to {file_path}")

    print("All subset files created successfully!")
