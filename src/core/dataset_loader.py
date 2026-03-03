import os
import logging
from git import Repo
from datasets import load_dataset
from config import settings

logger = logging.getLogger(__name__)

class DatasetLoader:
    def __init__(self, dataset_name="SWE-bench/SWE-bench_Lite"):
        self.dataset_name = dataset_name
        self.repo_root = settings.REPO_PATH
        self.dataset_root = settings.DATASET_PATH

    def load_data(self, split="test"):
        logger.info(f"Loading {self.dataset_name} ({split} split)...")
        # Downloads data to settings.DATASET_PATH
        return load_dataset(
            self.dataset_name, 
            split=split, 
            cache_dir=self.dataset_root,
            # Default mode: only downloads if missing or updated
            download_mode="reuse_dataset_if_exists" 
        )

    def load_repo(self, instance: dict):
        """
        Clones the repo and checks out the base_commit for a specific task.
        """
        repo_name = instance["repo"] # e.g., 'django/django'
        base_commit = instance["base_commit"]
        instance_id = instance["instance_id"]
        
        # Local path: data/repos/django__django
        local_repo_path = self.repo_root / repo_name.replace("/", "__")
        
        # Clone if not exists
        if not local_repo_path.exists():
            remote_url = f"https://github.com/{repo_name}.git"
            logger.info(f"Cloning {{repo_name}} to {{local_repo_path}}...")
            Repo.clone_from(remote_url, local_repo_path)
        
        repo = Repo(local_repo_path)
        
        # Reset and Checkout the base commit
        logger.info(f"Checking out base_commit {{base_commit}} for {{instance_id}}...")
        repo.git.reset("--hard")
        repo.git.clean("-fd")
        repo.git.checkout(base_commit)
        
        return local_repo_path