import sqlite3
import json
import os
from datetime import datetime
from src.core import settings

class DBLogger:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DBLogger, cls).__new__(cls)
        return cls._instance

    def __init__(self, db_path=None):
        if not DBLogger._initialized:
            self.db_path = db_path or (settings.DATA_DIR / "spade_results.db")
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
                    total_bugs INTEGER,
                    resolution_rate REAL,
                    fl_accuracy REAL,
                    pass_at_1 INTEGER,
                    debate_rescues_at_1 INTEGER,
                    inner_loop_rescues INTEGER,
                    outer_loop_rescues INTEGER,
                    avg_attempts_to_fix REAL,
                    total_cost REAL,
                    total_tokens INTEGER,
                    total_input_tokens INTEGER,
                    total_output_tokens INTEGER,
                    avg_cost_per_bug REAL,
                    total_duration_seconds REAL,
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
                    duration_seconds REAL,
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

    def _get_experiment_metrics(self, experiment_id: str = None) -> dict:
        """Calculates aggregated metrics for an experiment (or all if None)."""
        where_clause = ""
        params = []
        if experiment_id:
            where_clause = "WHERE experiment_id = ?"
            params = [experiment_id]
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 1. High-level Resolution Metrics
            cursor.execute(f"SELECT COUNT(*) as total_bugs, SUM(is_resolved) as resolved_bugs, SUM(fl_match) as fl_matches FROM repair_runs {where_clause}", params)
            row = cursor.fetchone()
            total_bugs = row['total_bugs'] or 0
            resolved_bugs = row['resolved_bugs'] or 0
            fl_matches = row['fl_matches'] or 0
            
            resolution_rate = (resolved_bugs / total_bugs * 100) if total_bugs > 0 else 0
            fl_accuracy = (fl_matches / total_bugs * 100) if total_bugs > 0 else 0
            
            # 2. Debate & Efficiency Metrics (only for patches that successfully passed tests)
            # Join with repair_runs to filter by experiment_id if needed
            patches_where = "WHERE p.tests_passed = 1"
            if experiment_id:
                patches_where += " AND r.experiment_id = ?"
            
            cursor.execute(f"""
                SELECT 
                    COUNT(CASE WHEN p.loop_n = 1 AND p.loop_m = 1 AND p.loop_v = 1 THEN 1 END) as pass_at_1,
                    COUNT(CASE WHEN p.loop_n = 1 AND p.loop_m = 1 AND p.loop_v > 1 THEN 1 END) as debate_rescues,
                    COUNT(CASE WHEN p.loop_n = 1 AND p.loop_m > 1 THEN 1 END) as inner_rescues,
                    COUNT(CASE WHEN p.loop_n > 1 THEN 1 END) as outer_rescues,
                    AVG(p.patch_version) as avg_attempts
                FROM patch_evaluations p
                JOIN repair_runs r ON p.run_id = r.run_id
                {patches_where}
            """, params)
            row = cursor.fetchone()
            pass_at_1 = row['pass_at_1'] or 0
            debate_rescues = row['debate_rescues'] or 0
            inner_rescues = row['inner_rescues'] or 0
            outer_rescues = row['outer_rescues'] or 0
            avg_attempts = row['avg_attempts'] or 0.0
            
            # 3. Cost & Telemetry
            telemetry_where = ""
            if experiment_id:
                telemetry_where = "WHERE r.experiment_id = ?"
            
            cursor.execute(f"""
                SELECT 
                    SUM(l.cost_usd) as total_cost, 
                    SUM(l.prompt_tokens) as total_in, 
                    SUM(l.completion_tokens) as total_out
                FROM llm_telemetry l
                JOIN repair_runs r ON l.run_id = r.run_id
                {telemetry_where}
            """, params)
            row = cursor.fetchone()
            total_cost = row['total_cost'] or 0.0
            total_in = row['total_in'] or 0
            total_out = row['total_out'] or 0
            total_tokens = total_in + total_out
            avg_cost = (total_cost / total_bugs) if total_bugs > 0 else 0.0
            
            # 4. Agent Breakdown
            cursor.execute(f"""
                SELECT l.agent_name, SUM(l.cost_usd) as total_cost, SUM(l.prompt_tokens) as prompt_t, SUM(l.completion_tokens) as comp_t
                FROM llm_telemetry l
                JOIN repair_runs r ON l.run_id = r.run_id
                {telemetry_where}
                GROUP BY l.agent_name
            """, params)
            agent_breakdown = [dict(r) for r in cursor.fetchall()]
            
            return {
                "total_bugs": total_bugs,
                "resolved_bugs": resolved_bugs,
                "resolution_rate": resolution_rate,
                "fl_accuracy": fl_accuracy,
                "pass_at_1": pass_at_1,
                "debate_rescues_at_1": debate_rescues,
                "inner_loop_rescues": inner_rescues,
                "outer_loop_rescues": outer_rescues,
                "avg_attempts": avg_attempts,
                "total_cost": total_cost,
                "total_tokens": total_tokens,
                "total_in": total_in,
                "total_out": total_out,
                "avg_cost": avg_cost,
                "agent_breakdown": agent_breakdown
            }

    def update_experiment_metrics(self, experiment_id: str):
        """Updates the experiments table with final aggregated metrics."""
        metrics = self._get_experiment_metrics(experiment_id)
        
        # Calculate total duration from DB timestamps
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT created_at FROM experiments WHERE experiment_id = ?", (experiment_id,))
            row = cursor.fetchone()
            if row:
                # SQLite CURRENT_TIMESTAMP is in '%Y-%m-%d %H:%M:%S' format
                created_at = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                total_duration = (datetime.utcnow() - created_at).total_seconds()
            else:
                total_duration = 0.0

            conn.cursor().execute("""
                UPDATE experiments SET 
                    total_bugs = ?, resolution_rate = ?, fl_accuracy = ?,
                    pass_at_1 = ?, debate_rescues_at_1 = ?, 
                    inner_loop_rescues = ?, outer_loop_rescues = ?,
                    avg_attempts_to_fix = ?, total_cost = ?, total_tokens = ?,
                    total_input_tokens = ?, total_output_tokens = ?, avg_cost_per_bug = ?,
                    total_duration_seconds = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE experiment_id = ?
            """, (
                metrics.get("total_bugs"), metrics.get("resolution_rate"), metrics.get("fl_accuracy"),
                metrics.get("pass_at_1"), metrics.get("debate_rescues_at_1"), 
                metrics.get("inner_loop_rescues"), metrics.get("outer_loop_rescues"),
                metrics.get("avg_attempts"), metrics.get("total_cost"), metrics.get("total_tokens"),
                metrics.get("total_in"), metrics.get("total_out"), metrics.get("avg_cost"),
                total_duration,
                experiment_id
            ))
    
    def start_repair_run(self, experiment_id: str, bug_id: str, run_id: str = None) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute(
                "INSERT OR IGNORE INTO repair_runs (run_id, experiment_id, bug_id) VALUES (?, ?, ?)",
                (run_id, experiment_id, bug_id)
            )
        return run_id

    def update_repair_run(self, run_id: str, fl_match: bool, is_resolved: bool, status: str):
        # Calculate duration from DB timestamps
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT created_at FROM repair_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if row:
                created_at = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                duration = (datetime.utcnow() - created_at).total_seconds()
            else:
                duration = 0.0

            conn.cursor().execute("""
                UPDATE repair_runs 
                SET fl_match = ?, is_resolved = ?, resolution_status = ?, duration_seconds = ?, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = ?
            """, (fl_match, is_resolved, status, duration, run_id))

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
