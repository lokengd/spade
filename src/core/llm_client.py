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
import requests
import yaml

T = TypeVar('T', bound=BaseModel)

class LLM_Client:
    def __init__(self, agent: str, provider: str, model: str, temperature: float = 0.0, base_url: str = None, api_key: str = None):
        self.agent_name = agent
        self.provider = provider
        self.model_name = model 
        self.temperature = temperature
        
        # Resolve API Key dynamically from the environment
        resolved_key = "dummy_key" 
        if api_key:
            env_key = os.environ.get(api_key)
            if env_key:
                resolved_key = env_key
            else:
                log(f"{api_key} is missing from environment variables!", caller=self.agent_name, level=logging.WARNING)

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
        
        # Add loop suffixes if available
        suffix = ""
        if loop_info:
            n = loop_info.get("n")
            m = loop_info.get("m")
            v = loop_info.get("v")
            
            if "Pattern_Selection" in clean_agent_name and n is not None:
                suffix = f"_n{n}"
            elif "PatchGen" in clean_agent_name and n is not None and m is not None and v is not None:
                suffix = f"_n{n}_m{m}_v{v}"
            # For other agents, use the full suffix if all info is present
            elif n is not None and m is not None and v is not None:
                suffix = f"_n{n}_m{m}_v{v}"
            elif n is not None:
                suffix = f"_n{n}"

        filename = f"{log_dir.name}_{clean_agent_name}{suffix}_traj.json"
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
                # think=False,
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

    def generate_json_response(self, system_prompt: str, user_prompt: str, response_model: Type[T], loop_info: Optional[dict] = None) -> Tuple[T, dict, dict]:
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
                # think=False,
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
            e.raw_json = raw_json
            raise





class OpenRouterClient(LLM_Client):
    """Minimal OpenRouter API client with optional streaming support."""
    DEFAULT_LLM_SETTINGS = {
        "model": "gpt-oss-120b:nitro", #"qwen3.5:9b", # qwen2.5-coder:14b # deepseek-r1:latest gpt-oss:20b gpt-oss-120b
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "repetition_penalty": 2.0,
    }

    def __init__(
        self,
        agent: str, 
        provider: str,
        api_key: str,
        model: str = DEFAULT_LLM_SETTINGS["model"],
        base_url: str = "https://openrouter.ai/api/v1",
        verbose: bool = False,
        temperature: float = DEFAULT_LLM_SETTINGS["temperature"],
        top_p: float = DEFAULT_LLM_SETTINGS["top_p"],
        top_k: int = DEFAULT_LLM_SETTINGS["top_k"],
        min_p: float = DEFAULT_LLM_SETTINGS["min_p"],
        presence_penalty: float = DEFAULT_LLM_SETTINGS["presence_penalty"],
        repetition_penalty: float = DEFAULT_LLM_SETTINGS["repetition_penalty"],
        stream: bool = False,
        site_url: str | None = None,
        app_name: str | None = None,
    ):
        self.agent_name = agent
        self.provider = provider
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/chat/completions"
        self.models_url = f"{self.base_url}/models"
        self.verbose = verbose
        self.stream = stream
        self.default_params = {
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": repetition_penalty,  # closest OpenRouter/OpenAI-compatible analog
        }

        if api_key:
            self.api_key = api_key
        else:
            def load_api_key():
                with open(settings.API_KEY_CONFIG_PATH, "r") as f:
                    return yaml.safe_load(f)
            api_key_config = load_api_key()
            self.api_key = api_key_config["openrouter"]["api_key"]

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # if site_url:
        #     self.headers["HTTP-Referer"] = site_url
        # if app_name:
        #     self.headers["X-Title"] = app_name
        self.caller = f"{self.agent_name}-{self.model_name}"

    def check_connection(self) -> bool:
        """Check API key and model availability."""
        try:
            resp = requests.get(self.models_url, headers=self.headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", [])]
            if self.model not in models:
                log(f"⚠ Model '{self.model}' not found via OpenRouter.", caller=self.caller)
                log(f"Available examples: {', '.join(models[:10])}", caller=self.caller)
                return False
            log(f"✅ OpenRouter connected. Model '{self.model}' ready.", caller=self.caller)
            return True
        except Exception as e:
            log(f"❌ Cannot connect to OpenRouter: {e}", caller=self.caller, level=logging.ERROR)
            return False

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        sample_id: int = 0,
    ) -> dict:
        """Generate completion from OpenRouter chat/completions."""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "effort": "low",
            # "stream": self.stream,
            # **self.default_params,
            # "temperature": temperature,  # override per-call
        }

        raw_output = ""
        usage = {"prompt_tokens": len(prompt) // 4, "completion_tokens": 0}

        response = requests.post(
            self.api_url,
            headers=self.headers,
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()
        raw_output = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        return {"response": raw_output, "usage": usage}
    
    def generate_json_response(self, system_prompt: str, user_prompt: str,response_model: Type[T], loop_info: Optional[dict] = None) -> Tuple[T, dict, dict]:
        """
        Forces the LLM to output its answer as a strict JSON object that matches a Pydantic schema (Type[T]).
        """
        raw_json = "No response received"
        try:
            log(f"System Prompt: <see trajectory>", caller=self.caller)    
            log(f"User Prompt: <see trajectory>", caller=self.caller)    
            # log(f"System Prompt: {system_prompt}", caller=self.agent_name)    
            # log(f"User Prompt: {user_prompt}", caller=self.agent_name)    


            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content":  user_prompt}],
                "max_tokens": 4096,
                "effort": "high",
                # "stream": self.stream,
                # **self.default_params,
                # "temperature": temperature,  # override per-call
            }

            raw_output = ""
            usage = {"prompt_tokens": 0, "completion_tokens": 0}

            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()
            raw_output = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            print(raw_output)
            parsed_data = response_model.model_validate_json(raw_output)

            # raw_json = response.choices[0].message.content
            metrics = {} # self._calculate_metrics(response.usage, 0)

            # print(raw_json)

            telemetry = self._save_trajectory(system_prompt, user_prompt, parsed_data, metrics, loop_info=loop_info)
            # telemetry = self._save_trajectory(system_prompt, user_prompt, json.loads(parsed_data), metrics, loop_info=loop_info)
            # parsed_data = response_model.model_validate_json(raw_json)
            # log(f"LLM structured response received. Duration: {metrics['total_seconds']}s", caller=self.model_name)
            # log(f"LLM response metrics: {metrics}", caller=self.model_name)

            return parsed_data, metrics, telemetry
        
        except Exception as e:
            log(f"LLM Structured Error (OpenRouter): {e}", caller=self.caller, level=logging.ERROR)
            log(f"Raw LLM Response that possibly caused the error: \n{raw_output}", caller=self.caller, level=logging.ERROR)
            e.raw_output = raw_output
            raise

    def generate_raw_response(self, system_prompt: str, user_prompt: str, loop_info: Optional[dict] = None) -> Tuple[T, dict, dict]:
        """
        Forces the LLM to output its answer as a strict JSON object that matches a Pydantic schema (Type[T]).
        """
        raw_json = "No response received"
        try:
            log(f"System Prompt: <see trajectory>", caller=self.caller)    
            log(f"User Prompt: <see trajectory>", caller=self.caller)
            # log(f"System Prompt: {system_prompt}", caller=self.agent_name)    
            # log(f"User Prompt: {user_prompt}", caller=self.agent_name)    


            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content":  user_prompt}],
                "max_tokens": 4096,
                "effort": "high",
                # "stream": self.stream,
                # **self.default_params,
                # "temperature": temperature,  # override per-call
            }

            raw_output = ""
            usage = {"prompt_tokens": 0, "completion_tokens": 0}

            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()
            raw_output = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # print(raw_output)

            # raw_json = response.choices[0].message.content
            metrics = {} # self._calculate_metrics(response.usage, 0)

            # print(raw_json)

            telemetry = self._save_trajectory(system_prompt, user_prompt, raw_output, metrics, loop_info=loop_info)
            # parsed_data = response_model.model_validate_json(raw_json)
            # log(f"LLM structured response received. Duration: {metrics['total_seconds']}s", caller=self.model_name)
            # log(f"LLM response metrics: {metrics}", caller=self.model_name)

            return raw_output, metrics, telemetry
        
        except Exception as e:
            log(f"LLM Structured Error (OpenRouter): {e}", caller=self.caller, level=logging.ERROR)
            log(f"Raw LLM Response that possibly caused the error: \n{raw_output}", caller=self.caller, level=logging.ERROR)
            e.raw_output = raw_output
            raise