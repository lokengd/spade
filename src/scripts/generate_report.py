import sqlite3
import pandas as pd
import os
import argparse
from datetime import datetime

def generate_metrics_report(db_path="data/spade_results.db", experiment_id=None, output_dir=None):
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        return

    # Default output directory if none provided
    if output_dir is None:
        output_dir = "data/reports"
        
    os.makedirs(output_dir, exist_ok=True)
    report_lines = []

    def report_print(msg):
        print(msg)
        report_lines.append(msg)

    with sqlite3.connect(db_path) as conn:
        # Filter by experiment if provided, otherwise aggregate all
        where_clause = f"WHERE experiment_id = '{experiment_id}'" if experiment_id else ""
        
        report_print("\n" + "="*50)
        report_print(f"SPADE EXPERIMENT REPORT: {experiment_id or 'ALL EXPERIMENTS'}")
        report_print("="*50)

        # High-Level Resolution Metrics
        runs_df = pd.read_sql_query(f"SELECT * FROM repair_runs {where_clause}", conn)
        total_bugs = len(runs_df)
        
        if total_bugs == 0:
            report_print("No data found for this experiment.")
            return

        resolved_bugs = runs_df['is_resolved'].sum()
        resolution_rate = (resolved_bugs / total_bugs) * 100 if total_bugs > 0 else 0
        fl_accuracy = (runs_df['fl_match'].sum() / total_bugs) * 100 if total_bugs > 0 else 0
        
        report_print(f"Total Bugs Processed : {total_bugs}")
        report_print(f"Resolution Rate      : {resolution_rate:.1f}% ({resolved_bugs}/{total_bugs})")
        report_print(f"FL Accuracy          : {fl_accuracy:.1f}%")

        # Debate & Efficiency Metrics (Pass@1 vs Multi-Agent) - only look at patches that successfully passed tests
        patches_df = pd.read_sql_query(f"""
            SELECT p.* FROM patch_evaluations p
            JOIN repair_runs r ON p.run_id = r.run_id
            WHERE p.tests_passed = 1 {f"AND r.experiment_id = '{experiment_id}'" if experiment_id else ""}
        """, conn)

        # Pass@1: Fixed on the first attempt (v=1)
        pass_at_1 = len(patches_df[patches_df['loop_v'] == 1]) if not patches_df.empty else 0
        pass_at_1_rate = (pass_at_1 / resolved_bugs) * 100 if resolved_bugs > 0 else 0
        
        # Efficacy of Debate: Required inner loop refinement (v > 1)
        debate_fixes = len(patches_df[patches_df['loop_v'] > 1]) if not patches_df.empty else 0
        debate_rate = (debate_fixes / resolved_bugs) * 100 if resolved_bugs > 0 else 0

        avg_attempts = patches_df['patch_version'].mean() if not patches_df.empty else 0.0

        report_print(f"Pass@1 (First Try)   : {pass_at_1_rate:.1f}% ({pass_at_1} bugs)")
        report_print(f"Debate Rescues (v>1) : {debate_rate:.1f}% ({debate_fixes} bugs)")
        report_print(f"Avg Attempts to Fix  : {avg_attempts:.1f} patches/bug")

        # Cost & Telemetry
        costs_df = pd.read_sql_query(f"""
            SELECT l.agent_name, SUM(l.cost_usd) as total_cost, SUM(l.prompt_tokens) as prompt_t, SUM(l.completion_tokens) as comp_t
            FROM llm_telemetry l
            JOIN repair_runs r ON l.run_id = r.run_id
            {where_clause}
            GROUP BY l.agent_name
        """, conn)

        total_cost = costs_df['total_cost'].sum()
        avg_cost_per_bug = total_cost / total_bugs if total_bugs > 0 else 0
        total_input_tokens = int(costs_df['prompt_t'].sum())
        total_output_tokens = int(costs_df['comp_t'].sum())
        total_tokens = total_input_tokens + total_output_tokens

        report_print(f"\nTotal Run Cost       : ${total_cost:.4f}")
        report_print(f"Total Tokens         : {total_tokens:,}")
        report_print(f"Total Input Tokens   : {total_input_tokens:,}")
        report_print(f"Total Output Tokens  : {total_output_tokens:,}")
        report_print(f"Avg Cost per Bug     : ${avg_cost_per_bug:.4f}")
        report_print(f"\nCost by Agent Breakdown:")
        
        for _, row in costs_df.iterrows():
            agent_in = int(row['prompt_t'])
            agent_out = int(row['comp_t'])
            agent_total = agent_in + agent_out
            report_print(f"  - {row['agent_name'].ljust(20)}: ${row['total_cost']:.4f}, Tokens: {agent_in:,} input + {agent_out:,} output = {agent_total:,} total")
            
        report_print("="*50 + "\n")

    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    exp_suffix = f"_{experiment_id}" if experiment_id else "_all"
    filename = f"spade_report{exp_suffix}_{timestamp}.txt"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        f.write("\n".join(report_lines))
    print(f"Report saved to: {os.path.abspath(filepath)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a textual metrics report from SPADE results.")
    parser.add_argument("--db", default="data/spade_results.db", help="Path to the SQLite database file (default: data/spade_results.db)")
    parser.add_argument("--exp", default=None, help="Experiment ID to filter by (default: None, aggregates all)")
    parser.add_argument("--out", default="data/reports", help="Directory to save the report (default: data/reports)")
    
    args = parser.parse_args()
    generate_metrics_report(db_path=args.db, experiment_id=args.exp, output_dir=args.out)