# src/core/llm_client.py
import logging
from typing import Type, TypeVar
from pydantic import BaseModel
from openai import OpenAI
from config import settings # Import centralized settings

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)

class LLM_Client:
    def __init__(self):
        """
        Initializes the LLM client using settings from config/settings.py
        """
        self.provider = settings.LLM_PROVIDER
        self.model_name = settings.LLM_MODEL_NAME
        
        if self.provider == "openai":
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
            
        elif self.provider == "gemini":
            self.client = OpenAI(
                api_key=settings.GEMINI_API_KEY,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            
        elif self.provider == "ollama":
            self.client = OpenAI(
                api_key="ollama", 
                base_url=settings.OLLAMA_BASE_URL
            )
            
        else:
            raise ValueError(f"Unsupported provider in settings: {self.provider}")

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = None) -> str:
        temp = temperature if temperature is not None else settings.LLM_TEMPERATURE_CREATIVE
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=temp,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM Text Generation Error ({self.provider}): {e}")
            raise

    def generate_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T], temperature: float = None) -> T:
        temp = temperature if temperature is not None else settings.LLM_TEMPERATURE_STABLE
        try:
            schema_instruction = (
                f"\n\nYou MUST return ONLY valid JSON matching this schema:\n"
                f"{response_model.model_json_schema()}"
            )
            
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=temp,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt + schema_instruction},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            raw_json = response.choices[0].message.content
            return response_model.model_validate_json(raw_json)
            
        except Exception as e:
            logger.error(f"LLM Structured Parsing Error ({self.provider}): {e}")
            raise