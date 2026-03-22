from src.evaluation.swe_bench_lite_utils import *
from src.evaluation.constants import ALL_INSTANCES, GOLD_PATCH


GOLD_PATCH_RESULTS_STORAGE_FOLDER_NAME = "gold_patch_results"
RUN_ID = "gold_patch_evaluation"


def get_script_dir() -> str:
    """Returns the directory of the currently executing script."""
    return Path(__file__).parent.resolve()


def get_gold_patch_results_storage_path() -> str:
    """Return script_dir / storage folder name for gold patch results."""
    return get_script_dir() / GOLD_PATCH_RESULTS_STORAGE_FOLDER_NAME


def make_gold_patch_results_storage_folder():
    """Creates a storage folder for gold patch results if it doesn't already exist."""
    storage_path = get_gold_patch_results_storage_path()
    storage_path.mkdir(exist_ok=True)
    return storage_path


def copy_dir_to_gold_patch_results(source_dir: str, instance_id: str):
    """Copies the contents of the source directory to a new directory named after the instance_id within the gold patch results storage folder."""
    print(f"Copying results for {instance_id} to gold patch results storage...")

    storage_path = get_gold_patch_results_storage_path()
    destination_dir = storage_path / instance_id

    if destination_dir.exists():
        shutil.rmtree(destination_dir)  # Remove existing directory if it exists

    shutil.copytree(source_dir, destination_dir)

    print(f"Copied results for {instance_id} to {destination_dir}")


def save_resolved_and_unresolved_instances(resolved_instances: List[str], unresolved_instances: List[str]):
    """Saves the lists of resolved and unresolved instances to text files in the gold patch results storage folder."""
    storage_path = get_gold_patch_results_storage_path()

    resolved_file = storage_path / "resolved_instances.txt"
    unresolved_file = storage_path / "unresolved_instances.txt"

    with open(resolved_file, "w") as f:
        for instance in resolved_instances:
            f.write(f"{instance}\n")

    with open(unresolved_file, "w") as f:
        for instance in unresolved_instances:
            f.write(f"{instance}\n")


def check_already_resolved_instances(instances: List[str]) -> List[str]:
    """Checks the gold patch results storage folder for any already resolved instances and returns a list of those instance IDs."""
    storage_path = get_gold_patch_results_storage_path()
    already_resolved_instances = []

    for instance in instances:
        instance_dir = storage_path / instance
        if instance_dir.exists() and instance_dir.is_dir():
            already_resolved_instances.append(instance)

    non_resolved_instances = [instance for instance in instances if instance not in already_resolved_instances]
    return already_resolved_instances, non_resolved_instances


if __name__ == "__main__":
    print("Starting evaluation of gold patches on all instances...")

    already_resolved_instances, non_resolved_instances = check_already_resolved_instances(ALL_INSTANCES)
    print(f"Already resolved instances: {already_resolved_instances}")
    print(f"Non-resolved instances to run: {non_resolved_instances}")

    make_gold_patch_results_storage_folder()

    resolved_instances = []
    unresolved_instances = []
    counter = 0

    print("Setting up evaluation environment...")
    
    setup_evaluation_environment()
    
    print("Environment setup complete!\nStarting evaluations...")

    for instance_id in ALL_INSTANCES:
        counter += 1

        if instance_id in already_resolved_instances:
            resolved_instances.append(instance_id)
            print(f"Skipping {instance_id} as it has already been resolved.")
            continue

        print(f"{counter}/{len(ALL_INSTANCES)}: Running evaluation for instance: {instance_id} with gold patch")

        result = run_evaluation_on_instance(instance_id, RUN_ID, GOLD_PATCH)

        print(f"Evaluation result for {instance_id} with gold patch: {result}\n")

        if result.evaluation_ran_successfully:
            if result.bug_resolved:
                resolved_instances.append(instance_id)

                copy_dir_to_gold_patch_results(get_instance_logs_dir(instance_id, RUN_ID, GOLD_PATCH), instance_id)
            else:
                unresolved_instances.append(instance_id)
        else:
            unresolved_instances.append(instance_id)

        print(f"Cleaning up logs, results and docker images for {instance_id} with gold patch.")
        cleanup_logs_and_results_for_run(RUN_ID)
        cleanup_sweb_docker_images()

        print(f"Result for {instance_id} with gold patch: {result.bug_resolved}\n")
    
    cleanup_evaluation_dir()
    save_resolved_and_unresolved_instances(resolved_instances, unresolved_instances)
    print("Evaluation complete. Cleaned up evaluation directory.")
