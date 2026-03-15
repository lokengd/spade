import os
import sys
import argparse
from datetime import datetime

# Add the project root to sys.path to allow running this script directly
# from the root or within the script directory.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.db_logger import db_logger

def generate_metrics_report(experiment_id=None, output_dir=None):
    # Default output directory if none provided
    if output_dir is None:
        output_dir = "data/reports"
        
    os.makedirs(output_dir, exist_ok=True)
    report_lines = []

    def report_print(msg):
        print(msg)
        report_lines.append(msg)

    # Get all experiments for the header listing
    all_exps = db_logger.get_all_experiments()
    
    report_print("\n" + "="*50)
    report_print(f"SPADE EXPERIMENT REPORT: {experiment_id or 'ALL EXPERIMENTS'}")
    report_print("="*50)

    report_print(f"Experiments ({len(all_exps)}):")
    for exp in all_exps:
        active_marker = " [SELECTED]" if experiment_id == exp['experiment_id'] else ""
        report_print(f"  - {exp['experiment_id']} ({exp['created_at']}){active_marker}")

    # Calculate metrics using the common DBLogger method
    stats = db_logger.get_experiment_metrics(experiment_id)
    
    total_bugs = stats["total_bugs"]
    if total_bugs == 0:
        report_print("\nNo data found for this selection.")
        return

    report_print(f"\nTotal Bugs       : {total_bugs}")
    report_print(f"Resolution Rate  : {stats['resolution_rate']:.1f}% ({stats['resolved_bugs']}/{total_bugs})")
    report_print(f"FL Accuracy      : {stats['fl_accuracy']:.1f}%")

    report_print(f"Pass@1 (First Try)   : {(stats['pass_at_1']/stats['resolved_bugs']*100 if stats['resolved_bugs']>0 else 0):.1f}% ({stats['pass_at_1']} bugs)")
    report_print(f"Debate Rescues (v>1) : {(stats['debate_rescues']/stats['resolved_bugs']*100 if stats['resolved_bugs']>0 else 0):.1f}% ({stats['debate_rescues']} bugs)")
    report_print(f"Inner Loop Rescues   : {stats['inner_rescues']} bugs (M > 1)")
    report_print(f"Outer Loop Rescues   : {stats['outer_rescues']} bugs (N > 1)")
    report_print(f"Avg Attempts to Fix  : {stats['avg_attempts']:.1f} patches/bug")

    report_print(f"\nTotal Tokens        : {stats['total_tokens']:,}")
    report_print(f"Total Input Tokens  : {stats['total_in']:,}")
    report_print(f"Total Output Tokens : {stats['total_out']:,}")
    report_print(f"Total Cost          : ${stats['total_cost']:.4f}")
    report_print(f"Avg Cost per Bug    : ${stats['avg_cost']:.4f}")
    
    report_print(f"\nCost by Agent Breakdown:")
    for agent in stats["agent_breakdown"]:
        agent_in = agent['prompt_t']
        agent_out = agent['comp_t']
        agent_total = agent_in + agent_out
        report_print(f"  - {agent['agent_name'].ljust(20)}: ${agent['total_cost']:.4f}, Tokens: {agent_in:,} input + {agent_out:,} output = {agent_total:,} total")
            
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
    parser.add_argument("--exp", default=None, help="Experiment ID to filter by (default: None, aggregates all)")
    parser.add_argument("--out", default="data/reports", help="Directory to save the report (default: data/reports)")
    
    args = parser.parse_args()
    generate_metrics_report(experiment_id=args.exp, output_dir=args.out)
