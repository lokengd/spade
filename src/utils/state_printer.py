import json
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel
from src.core.state import SpadeState, BugContext, PatchCandidate, EvaluationResult, EditLocation

class StatePrinter:
    def __init__(self, indent_size: int = 4):
        self.indent_size = indent_size

    def _format_value(self, value: Any, indent: int = 0) -> str:
        current_indent = " " * indent
        next_indent = " " * (indent + self.indent_size)

        if isinstance(value, BaseModel):
            return self._format_dict(value.model_dump(), indent)
        elif isinstance(value, dict):
            return self._format_dict(value, indent)
        elif isinstance(value, list):
            if not value:
                return "[]"
            formatted_items = []
            for item in value:
                formatted_items.append(f"{next_indent}- {self._format_value(item, indent + self.indent_size).strip()}")
            return "\n" + "\n".join(formatted_items)
        elif isinstance(value, str):
            if "\n" in value:
                # Handle multi-line strings (like code diffs or error traces) - NO TRUNCATION
                lines = value.strip().split("\n")
                formatted_lines = [f"{next_indent}{line}" for line in lines]
                return "\n" + "\n".join(formatted_lines)
            return f'"{value}"'
        else:
            return str(value)

    def _format_dict(self, d: Dict[str, Any], indent: int = 0) -> str:
        next_indent = " " * (indent + self.indent_size)
        lines = []
        for key, value in d.items():
            formatted_val = self._format_value(value, indent + self.indent_size)
            if "\n" in formatted_val:
                lines.append(f"{next_indent}{key}:{formatted_val}")
            else:
                lines.append(f"{next_indent}{key}: {formatted_val}")
        return "\n" + "\n".join(lines)

    def print_state(self, state: SpadeState):
        print("=" * 80)
        print(" SPADE STATE ".center(80, "="))
        print("=" * 80)

        printed_keys = set()

        # 1. Basic Info
        basic_keys = [
            "thread_id", "experiment_id", "resolution_status", 
            "outer_loop_count", "inner_loop_count", "current_patch_version"
        ]
        for key in basic_keys:
            if key in state:
                print(f"{key.upper():<30}: {state[key]}")
                printed_keys.add(key)

        # 2. Bug Context
        if "bug_context" in state:
            print("-" * 80)
            print(" BUG CONTEXT ".center(80, "-"))
            bc = state["bug_context"]
            bc_dict = bc.model_dump() if isinstance(bc, BaseModel) else bc
            
            for k, v in bc_dict.items():
                print(f"  {k.upper():<28}: {self._format_value(v, 30).strip()}")
            printed_keys.add("bug_context")

        # 3. Patterns
        pattern_keys = ["selected_patterns", "active_pattern"]
        print("-" * 80)
        print(" PATTERNS ".center(80, "-"))
        for key in pattern_keys:
            if key in state:
                print(f"  {key.upper():<28}: {state[key]}")
                printed_keys.add(key)

        # 4. Evaluation Results (Reproduction)
        if "reproduction_evaluation_result" in state:
            print("-" * 80)
            print(" REPRODUCTION RESULT ".center(80, "-"))
            self._print_eval_result(state["reproduction_evaluation_result"])
            printed_keys.add("reproduction_evaluation_result")

        # 5. Patches
        patch_keys = [("v1_patches", "V1 PATCHES"), ("refined_patches", "REFINED PATCHES")]
        for patch_key, label in patch_keys:
            patches = state.get(patch_key, [])
            if patches:
                print("-" * 80)
                print(f" {label} ({len(patches)}) ".center(80, "-"))
                for patch in patches:
                    self._print_patch(patch)
                printed_keys.add(patch_key)

        # 6. Patch Evaluations
        eval_keys = [
            ("v1_patches_evaluation_result", "V1 PATCH EVALUATIONS"),
            ("refined_patch_evaluation_result", "REFINED PATCH EVALUATION")
        ]
        for eval_key, label in eval_keys:
            eval_res = state.get(eval_key)
            if eval_res:
                print("-" * 80)
                print(f" {label} ".center(80, "-"))
                if isinstance(eval_res, list):
                    for i, res in enumerate(eval_res):
                        print(f"  [Result {i}]")
                        self._print_eval_result(res)
                else:
                    self._print_eval_result(eval_res)
                printed_keys.add(eval_key)

        # 7. Arguments & Verdicts
        arg_keys = ["current_v1_id", "verdict", "dynamic_argument", "static_argument", 
                    "dynamic_rebuttal", "static_rebuttal", "historical_verdicts"]
        print("-" * 80)
        print(" ARGUMENTS & VERDICTS ".center(80, "-"))
        for key in arg_keys:
            if state.get(key):
                val = state[key]
                if isinstance(val, str) and (val.startswith("{") or val.startswith("```json")):
                    print(f"  {key.upper()}:")
                    try:
                        clean_json = val.replace("```json\n", "").replace("\n```", "").strip()
                        parsed = json.loads(clean_json)
                        print(json.dumps(parsed, indent=4).replace("\n", "\n    "))
                    except:
                        print(f"    {val}")
                else:
                    print(f"  {key.upper():<28}: {self._format_value(val, 30).strip()}")
                printed_keys.add(key)

        # 8. Metrics
        if "total_metrics" in state:
            print("-" * 80)
            print(" METRICS ".center(80, "-"))
            metrics = state.get("total_metrics", {})
            for mk, mv in metrics.items():
                print(f"  {mk:<30}: {mv}")
            printed_keys.add("total_metrics")

        # 9. Other Fields (Catch-all)
        other_keys = [k for k in state.keys() if k not in printed_keys]
        if other_keys:
            print("-" * 80)
            print(" OTHER FIELDS ".center(80, "-"))
            for key in other_keys:
                print(f"  {key.upper():<28}: {self._format_value(state[key], 30).strip()}")

        print("=" * 80)

    def print_trajectory(self, trajectory: List[Dict]):
        print("=" * 80)
        print(f" SPADE TRAJECTORY ({len(trajectory)} steps) ".center(80, "="))
        print("=" * 80)

        for i, step in enumerate(trajectory):
            print(f" STEP {i+1} ".center(80, "-"))
            print(f"TIMESTAMP: {step.get('timestamp')}")
            loop = step.get('loop_info', {})
            print(f"LOOP: N={loop.get('n')} M={loop.get('m')} V={loop.get('v')}")
            print(f"MODEL: {step.get('model')} ({step.get('provider')})")
            
            if 'prompts' in step:
                print(" PROMPTS ".center(40, "."))
                for p_key, p_val in step['prompts'].items():
                    print(f"  {p_key.upper()}:")
                    lines = str(p_val).strip().split("\n")
                    for line in lines:
                        print(f"      {line}")
            
            if 'response' in step:
                print(" RESPONSE ".center(40, "."))
                resp = step['response']
                if isinstance(resp, dict):
                    for r_key, r_val in resp.items():
                        print(f"  {r_key.upper()}:")
                        lines = str(r_val).strip().split("\n")
                        for line in lines:
                            print(f"      {line}")
                else:
                    print(f"  {resp}")

            if 'metrics' in step:
                print(" METRICS ".center(40, "."))
                print(f"    {step['metrics']}")
            
            # Print any other fields in the step
            other_step_keys = [k for k in step.keys() if k not in ['timestamp', 'loop_info', 'model', 'provider', 'prompts', 'response', 'metrics']]
            for osk in other_step_keys:
                print(f"  {osk.upper()}: {self._format_value(step[osk], 6).strip()}")
                
            print()
        print("=" * 80)

    def _print_patch(self, patch: Union[PatchCandidate, Dict]):
        if isinstance(patch, PatchCandidate):
            p = patch
        else:
            p = PatchCandidate(**patch)
        
        print(f"  PATCH ID: {p.id} | STRATEGY: {p.strategy} | STATUS: {p.status} | VERSION: {p.version}")
        # Show ALL lines of diff - NO TRUNCATION
        diff_lines = p.code_diff.strip().split("\n")
        full_diff = "\n".join([f"    {l}" for l in diff_lines])
        print(full_diff)
        print()

    def _print_eval_result(self, res: Union[EvaluationResult, Dict]):
        if isinstance(res, EvaluationResult):
            r = res
        else:
            r = EvaluationResult(**res)
        
        print(f"  SUCCESSFUL: {r.evaluation_ran_successfully} | RESOLVED: {r.bug_resolved}")
        print(f"  TESTS: Total={r.total_tests} | FTP Success={r.fail_to_pass_success} | PTP Success={r.pass_to_pass_success}")
        
        # Print all fields of EvaluationResult
        res_dict = r.model_dump() if isinstance(r, BaseModel) else r
        for k, v in res_dict.items():
            if k not in ['evaluation_ran_successfully', 'bug_resolved', 'total_tests', 'fail_to_pass_success', 'pass_to_pass_success']:
                if v is not None and v != [] and v != {}:
                    print(f"  {k.upper():<28}: {self._format_value(v, 30).strip()}")

def pretty_print_state(state: Union[Dict, List]):
    printer = StatePrinter()
    if isinstance(state, list):
        printer.print_trajectory(state)
    else:
        printer.print_state(state)
