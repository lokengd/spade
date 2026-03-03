import os
import logging
from typing import Type, TypeVar, Tuple
from pydantic import BaseModel
from openai import OpenAI
from config.settings import COST_TABLE

logger = logging.getLogger(__name__)
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
                logger.warning(f"{api_key_env} is missing from environment variables!")

        # Initialize the appropriate client based on provider
        client_kwargs = {"api_key": resolved_key}
        if base_url:
            client_kwargs["base_url"] = base_url
            
        # Initialize 
        self.client = OpenAI(**client_kwargs)


    def _calculate_metrics(self, usage) -> dict:
        if not usage:
            return {}
            
        p_tokens = getattr(usage, 'prompt_tokens', 0)
        c_tokens = getattr(usage, 'completion_tokens', 0)
        
        rates = COST_TABLE.get(self.model_name, {"input": 0.0, "output": 0.0})
        cost_usd = (p_tokens / 1_000_000 * rates["input"]) + (c_tokens / 1_000_000 * rates["output"])
        
        return {
            "total_prompt_tokens": p_tokens,
            "total_completion_tokens": c_tokens,
            "total_cost_usd": cost_usd,
            f"calls_{self.model_name}": 1
        }

    def generate_text(self, system_prompt: str, user_prompt: str) -> Tuple[str, dict]:
        """Returns a simple, unstructured Python string (str)."""

        logger.info(f"[{self.agent_name}] System Prompt: {system_prompt}")    
        logger.info(f"[{self.agent_name}] User Prompt: {user_prompt}")    

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            text_response = response.choices[0].message.content
            logger.info(f"[{self.agent_name}] LLM response:\n {text_response}\n")

            metrics = self._calculate_metrics(response.usage)
            logger.info(f"[{self.agent_name}] LLM response metrics: {metrics}")

            return text_response, metrics
        
        except Exception as e:
            logger.error(f"[{self.agent_name}] LLM Text Gen Error ({self.provider}): {e}")
            raise

    def generate_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T]) -> Tuple[T, dict]:
        """
        Forces the LLM to output its answer as a strict JSON object that matches a Pydantic schema (Type[T]).
        """
        try:
            logger.info(f"[{self.agent_name}] System Prompt: {system_prompt}")    
            logger.info(f"[{self.agent_name}] User Prompt: {user_prompt}")    

            schema_instruction = f"\n\nYou MUST return ONLY valid JSON matching this schema:\n{response_model.model_json_schema()}"
            
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=self.temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt + schema_instruction},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            raw_json = response.choices[0].message.content
            logger.info(f"[{self.agent_name}] LLM raw response:\n {raw_json}\n")

            parsed_data = response_model.model_validate_json(raw_json)
            logger.info(f"[{self.agent_name}] LLM json response:\n {parsed_data}\n")

            metrics = self._calculate_metrics(response.usage)
            logger.info(f"[{self.agent_name}] LLM response metrics: {metrics}")

            return parsed_data, metrics
        
        except Exception as e:
            logger.error(f"[{self.agent_name}] LLM Structured Error ({self.provider}): {e}")
            raise