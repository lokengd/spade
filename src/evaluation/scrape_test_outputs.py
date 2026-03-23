from src.evaluation.swe_bench_lite_utils import *
from src.evaluation.constants import ALL_INSTANCES


RESULTS_STORAGE_FOLDER_NAME = "instance_test_outputs"
RUN_ID = "scrape_test_outputs"


def get_script_dir() -> str:
    """Returns the directory of the currently executing script."""
    return Path(__file__).parent.resolve()


def get_repo_root() -> str:
    return Path(__file__).resolve().parents[2]


def get_results_storage_path() -> str:
    """Return script_dir / storage folder name for test outputs."""
    return get_repo_root() / RESULTS_STORAGE_FOLDER_NAME


def make_results_storage_folder():
    """Creates a storage folder for test outputs if it doesn't already exist."""
    storage_path = get_results_storage_path()
    storage_path.mkdir(exist_ok=True)

    print(f"Created test outputs storage folder at {storage_path}")

    return storage_path


def save_resolved_and_unresolved_instances(resolved_instances: List[str], unresolved_instances: List[str]):
    """Saves the lists of resolved and unresolved instances to text files in the test outputs storage folder."""
    storage_path = get_script_dir()

    resolved_file = storage_path / "scraping_resolved_instances.txt"
    unresolved_file = storage_path / "scraping_unresolved_instances.txt"

    with open(resolved_file, "w") as f:
        for instance in resolved_instances:
            f.write(f"{instance}\n")

    with open(unresolved_file, "w") as f:
        for instance in unresolved_instances:
            f.write(f"{instance}\n")
    
    print(f"Saved resolved instances to {resolved_file} and unresolved instances to {unresolved_file}")


def save_test_output_and_report_for_instance(instance_id: str, test_output: str, report_data: dict):
    """Saves the test output and report data for a given instance to the test outputs storage folder."""
    storage_path = get_results_storage_path()
    file_path = storage_path / f"{instance_id}.json"

    # Save in json format
    with open(file_path, "w") as f:
        json.dump({"filtered_test_output": "", "full_test_output": test_output, "report_data": report_data}, f, indent=4)
    
    print(f"Saved test output and report data for {instance_id} to {file_path}")


def get_scraped_and_non_scraped_instances(instances: List[str]) -> Tuple[List[str], List[str]]:
    """Checks the test outputs storage folder for which instances have scraped test outputs and which do not, and returns two lists: one for scraped instances and one for non-scraped instances."""
    storage_path = get_results_storage_path()
    scraped_instances = []
    non_scraped_instances = []

    for instance in instances:
        file_path = storage_path / f"{instance}.json"
        if file_path.exists():
            scraped_instances.append(instance)
        else:
            non_scraped_instances.append(instance)

    print(f"Scraped instances: {len(scraped_instances)}, Non-scraped instances: {len(non_scraped_instances)}")

    return scraped_instances, non_scraped_instances

if __name__ == "__main__":
    print("Starting scraping of all instances...")
    already_scraped_instances, non_scraped_instances = get_scraped_and_non_scraped_instances(ALL_INSTANCES)

    make_results_storage_folder()

    resolved_instances = []
    unresolved_instances = []
    counter = 0

    print("Setting up evaluation environment...")
    
    setup_evaluation_environment()
    
    print("Environment setup complete!\nStarting scraping...")

    for instance_id in ALL_INSTANCES:
        counter += 1

        if instance_id in already_scraped_instances:
            resolved_instances.append(instance_id)
            print(f"Skipping {instance_id} as it has already been scraped.")
            continue

        print(f"{counter}/{len(ALL_INSTANCES)}: Running evaluation for instance: {instance_id} for scraping test outputs...")

        result = run_evaluation_with_no_patch(instance_id, RUN_ID)

        print(f"Evaluation result for {instance_id}: {result}\n")

        if not result.evaluation_ran_successfully:
            unresolved_instances.append(instance_id)
        else:
            resolved_instances.append(instance_id)
        
            report_file_data = get_report_file(get_report_path(instance_id, RUN_ID, "predictions_path_placeholder"))["report_data"]
            test_output = result.test_output

            print(f"Saving test output and report data for {instance_id} to storage folder.")

            save_test_output_and_report_for_instance(instance_id, test_output, report_file_data)

        print(f"Cleaning up logs, results and docker images for {instance_id}.")
        cleanup_logs_and_results_for_run(RUN_ID)
        cleanup_sweb_docker_images()

        print(f"Result for {instance_id}: {result.bug_resolved}\n")

    print("Scraping complete. Saving resolved and unresolved instances and cleaning up evaluation directory.")

    cleanup_evaluation_dir()
    save_resolved_and_unresolved_instances(resolved_instances, unresolved_instances)

    print("Resolved instances:", len(resolved_instances))
    print("Unresolved instances:", len(unresolved_instances))

    print("Evaluation complete. Cleaned up evaluation directory.")
