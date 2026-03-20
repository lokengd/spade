import os
import json
import time
from datetime import datetime
from typing import Type, TypeVar, Tuple, Optional, Any
from pydantic import BaseModel
from openai import OpenAI
from src.core import settings
from src.utils.logger import log, get_current_log_dir
from src.utils.state_printer import pretty_print_state
import logging

T = TypeVar('T', bound=BaseModel)

class LLM_Client:
    def __init__(self, agent: str, provider: str, model: str, temperature: float = 0.0, base_url: str = None, api_key_env: str = None):
        self.agent_name = agent
        self.provider = provider
        self.model_name = model 
        self.temperature = temperature
        
        # Resolve API Key dynamically from the environment
        resolved_key = "dummy_key" 
        if api_key_env:
            env_key = os.environ.get(api_key_env)
            if env_key:
                resolved_key = env_key
            else:
                log(f"{api_key_env} is missing from environment variables!", caller=self.agent_name, level=logging.WARNING)

        # Initialize the appropriate client based on provider
        client_kwargs = {"api_key": resolved_key}
        if base_url:
            client_kwargs["base_url"] = base_url
            
        # Initialize 
        self.client = OpenAI(**client_kwargs)


    def _calculate_metrics(self, usage, duration: float) -> dict:
        if not usage:
            return {"total_seconds": round(duration, 3)}
            
        p_tokens = getattr(usage, 'prompt_tokens', 0)
        c_tokens = getattr(usage, 'completion_tokens', 0)
        
        rates = settings.COST_TABLE.get(self.model_name, {"input": 0.0, "output": 0.0})
        cost_usd = (p_tokens / 1_000_000 * rates["input"]) + (c_tokens / 1_000_000 * rates["output"])
        
        return {
            "total_prompt_tokens": p_tokens,
            "total_completion_tokens": c_tokens,
            "total_cost_usd": cost_usd,
            "total_seconds": round(duration, 3),
            f"calls_{self.model_name}": 1
        }

    def _save_trajectory(self, system_prompt: str, user_prompt: str, response: Any, metrics: dict, loop_info: Optional[dict] = None) -> dict:
        """Appends the LLM interaction to a JSON file and a pretty-printed TXT file within the thread's log directory."""
        log_dir = get_current_log_dir()
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "loop_info": loop_info, # Includes n, m, v
            "model": self.model_name,
            "provider": self.provider,
            "prompts": {
                "system": system_prompt,
                "user": user_prompt
            },
            "response": response,
            "metrics": metrics
        }

        # Generate pretty-printed output
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        try:
            with redirect_stdout(f):
                pretty_print_state([entry])
            pretty_output = f.getvalue()
            # Print to console for immediate feedback
            print(pretty_output)
        except Exception as e:
            log(f"Failed to pretty print trajectory: {e}", caller=self.agent_name, level=logging.WARNING)
            pretty_output = None

        if not log_dir:
            return entry

        # Format the trajectory filename: <folder_name>_<agent_name>_traj.json
        clean_agent_name = self.agent_name.replace("] [", "_").replace("[", "").replace("]", "").replace(" ", "_")
        filename = f"{log_dir.name}_{clean_agent_name}_traj.json"
        filepath = log_dir / filename
        txt_filepath = filepath.with_suffix(".txt")

        # Save to JSON (Append to list)
        data = []
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as f_json:
                    data = json.load(f_json)
                    if not isinstance(data, list):
                        data = [data]
            except Exception as e:
                log(f"Failed to load existing trajectory: {e}", caller=self.agent_name, level=logging.WARNING)
                data = []

        data.append(entry)

        try:
            with open(filepath, "w", encoding="utf-8") as f_json:
                json.dump(data, f_json, indent=2)
            
            # Save to TXT (Append pretty output)
            if pretty_output:
                with open(txt_filepath, "a", encoding="utf-8") as f_txt:
                    f_txt.write(pretty_output)
                    f_txt.write("\n" + "="*80 + "\n\n") # Separator between interactions

            log(f"Trajectory saved to {filepath} and {txt_filepath}", caller=self.agent_name, level=logging.DEBUG)
        except Exception as e:
            log(f"Failed to save trajectory: {e}", caller=self.agent_name, level=logging.ERROR)
            
        return entry

    def generate_text(self, system_prompt: str, user_prompt: str, loop_info: Optional[dict] = None) -> Tuple[str, dict, dict]:
        """Returns a simple, unstructured Python string (str), metrics, and raw telemetry."""

        log(f"System Prompt: <see trajectory>", caller=self.agent_name)    
        log(f"User Prompt: <see trajectory>", caller=self.agent_name)    
        # log(f"System Prompt: {system_prompt}", caller=self.agent_name)    
        # log(f"User Prompt: {user_prompt}", caller=self.agent_name)    

        try:
            start_time = time.time()
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            duration = time.time() - start_time
            
            text_response = response.choices[0].message.content
            metrics = self._calculate_metrics(response.usage, duration)

            telemetry = self._save_trajectory(system_prompt, user_prompt, text_response, metrics, loop_info=loop_info)
            
            log(f"LLM response received. Duration: {metrics['total_seconds']}s", caller=self.agent_name)
            log(f"LLM response metrics: {metrics}", caller=self.agent_name)

            return text_response, metrics, telemetry
        
        except Exception as e:
            log(f"LLM Text Gen Error ({self.provider}): {e}", caller=self.agent_name, level=logging.ERROR)
            raise

    def generate_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T], loop_info: Optional[dict] = None) -> Tuple[T, dict, dict]:
        """
        Forces the LLM to output its answer as a strict JSON object that matches a Pydantic schema (Type[T]).
        """
        raw_json = "No response received"
        try:
            log(f"System Prompt: <see trajectory>", caller=self.agent_name)    
            log(f"User Prompt: <see trajectory>", caller=self.agent_name)    
            # log(f"System Prompt: {system_prompt}", caller=self.agent_name)    
            # log(f"User Prompt: {user_prompt}", caller=self.agent_name)    
            
            start_time = time.time()
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=self.temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            duration = time.time() - start_time
            
            raw_json = response.choices[0].message.content
            metrics = self._calculate_metrics(response.usage, duration)

            telemetry = self._save_trajectory(system_prompt, user_prompt, json.loads(raw_json), metrics, loop_info=loop_info)
            parsed_data = response_model.model_validate_json(raw_json)
            log(f"LLM structured response received. Duration: {metrics['total_seconds']}s", caller=self.agent_name)
            log(f"LLM response metrics: {metrics}", caller=self.agent_name)

            return parsed_data, metrics, telemetry
        
        except Exception as e:
            log(f"LLM Structured Error ({self.provider}): {e}", caller=self.agent_name, level=logging.ERROR)
            log(f"Raw LLM Response that possibly caused the error: \n{raw_json}", caller=self.agent_name, level=logging.ERROR)
            raise
