import sqlite3
import json
import os
from datetime import datetime
from config.settings import DATA_DIR

class DBLogger:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DBLogger, cls).__new__(cls)
        return cls._instance

    def __init__(self, db_path=None):
        if not DBLogger._initialized:
            self.db_path = db_path or (DATA_DIR / "spade_results.db")
            # Ensure parent dir exists
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._init_db()
            DBLogger._initialized = True

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            """
            Database Schema
            """
            # 1. Experiments
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    description TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 2. Repair Runs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS repair_runs (
                    run_id TEXT PRIMARY KEY,
                    experiment_id TEXT,
                    bug_id TEXT NOT NULL,
                    fl_match BOOLEAN,
                    is_resolved BOOLEAN DEFAULT 0,
                    resolution_status TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                )
            """)
            
            # 3. LLM Telemetry
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_telemetry (
                    telemetry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    agent_name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    loop_n INTEGER, 
                    loop_m INTEGER, 
                    loop_v INTEGER,
                    prompt_tokens INTEGER, 
                    completion_tokens INTEGER,
                    cost_usd REAL, 
                    duration_seconds REAL,
                    prompt_json TEXT, 
                    response_json TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES repair_runs(run_id)
                )
            """)
            
            # 4. Patch Evaluations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patch_evaluations (
                    patch_id TEXT PRIMARY KEY,
                    patch_version INTEGER,
                    run_id TEXT,
                    loop_n INTEGER,
                    loop_m INTEGER,
                    loop_v INTEGER,
                    pattern_applied TEXT,
                    patch_diff TEXT,
                    tests_passed BOOLEAN DEFAULT 0, -- Is it "Plausible"? (not correctness, just whether it passes tests)
                    previous_feedback TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES repair_runs(run_id)
                );             
            """)
            conn.commit()

    def start_experiment(self, experiment_id: str, description: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute(
                "INSERT OR IGNORE INTO experiments (experiment_id, description) VALUES (?, ?)",
                (experiment_id, description)
            )

    def start_repair_run(self, experiment_id: str, bug_id: str, run_id: str = None) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute(
                "INSERT OR IGNORE INTO repair_runs (run_id, experiment_id, bug_id) VALUES (?, ?, ?)",
                (run_id, experiment_id, bug_id)
            )
        return run_id

    def update_repair_run(self, run_id: str, fl_match: bool, is_resolved: bool, status: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute("""
                UPDATE repair_runs 
                SET fl_match = ?, is_resolved = ?, resolution_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = ?
            """, (fl_match, is_resolved, status, run_id))

    def log_telemetry(self, run_id: str, agent_name: str, log_data: dict) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO llm_telemetry (
                    run_id, agent_name, model, provider, 
                    loop_n, loop_m, loop_v,
                    prompt_tokens, completion_tokens, cost_usd, duration_seconds,
                    prompt_json, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, agent_name, log_data["model"], log_data["provider"],
                log_data["loop_info"]["n"], log_data["loop_info"]["m"], log_data["loop_info"]["v"],
                log_data["metrics"]["total_prompt_tokens"], log_data["metrics"]["total_completion_tokens"],
                log_data["metrics"]["total_cost_usd"], log_data["metrics"]["total_seconds"],
                json.dumps(log_data["prompts"]), json.dumps(log_data["response"])
            ))
            return cursor.lastrowid

    def log_patch(self, patch_id: str, run_id: str, patch_version: int, loop_n: int, loop_m: int, loop_v: int, pattern: str, diff: str, tests_passed: bool = False, feedback: str = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute("""
                INSERT OR REPLACE INTO patch_evaluations (
                    patch_id, run_id, patch_version, 
                    loop_n, loop_m, loop_v, pattern_applied, patch_diff, tests_passed, previous_feedback, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (patch_id, run_id, patch_version, loop_n, loop_m, loop_v, pattern, diff, tests_passed, feedback))

    def update_patch(self, patch_id: str, tests_passed: bool):
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute("""
                UPDATE patch_evaluations
                SET tests_passed = ?, updated_at = CURRENT_TIMESTAMP
                WHERE patch_id = ?
            """, (tests_passed, patch_id))

# Global instance
db_logger = DBLogger()
