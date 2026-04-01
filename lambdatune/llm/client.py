"""
LLM client abstraction for λ-Tune.

This module provides a unified interface for interacting with different LLM providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
import logging
import time
from pathlib import Path
import json

logger = logging.getLogger(__name__)

@dataclass
class LLMResponse:
    """Data class to store LLM response data."""
    content: str
    tokens_used: int
    model: str
    provider: str
    metadata: Dict[str, Any] = None
    timestamp: float = time.time()

class LLMClient(ABC):
    """
    Abstract base class for LLM clients.
    
    This class defines the interface that all LLM clients must implement.
    It provides a common contract for interacting with different LLM providers.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
        presence_penalty: float = 0.0,
        stop: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize the LLM client.
        
        Args:
            api_key: API key for the LLM provider
            model: Model name to use
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling parameter
            frequency_penalty: Frequency penalty
            presence_penalty: Presence penalty
            stop: Stop sequences
            **kwargs: Additional provider-specific parameters
        """
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.stop = stop
        self.kwargs = kwargs
        self._rate_limit_remaining = None
        self._rate_limit_reset = None

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate text from a prompt.
        
        Args:
            prompt: The prompt to generate from
            system_prompt: Optional system prompt
            **kwargs: Additional generation parameters
            
        Returns:
            LLMResponse object containing the generated text
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Count the number of tokens in a text.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Number of tokens in the text
        """
        pass

    @abstractmethod
    def get_available_models(self) -> List[str]:
        """
        Get list of available models.
        
        Returns:
            List of available model names
        """
        pass

    def _validate_parameters(self) -> None:
        """Validate client parameters."""
        if not self.api_key:
            raise ValueError("API key is required")

        if not self.model:
            raise ValueError("Model name is required")

        if self.temperature < 0 or self.temperature > 2:
            raise ValueError("Temperature must be between 0 and 2")

        if self.top_p < 0 or self.top_p > 1:
            raise ValueError("Top-p must be between 0 and 1")

    def _handle_rate_limit(self) -> None:
        """Handle rate limiting."""
        if self._rate_limit_remaining is not None and self._rate_limit_remaining <= 0:
            if self._rate_limit_reset:
                wait_time = self._rate_limit_reset - time.time()
                if wait_time > 0:
                    logger.warning(f"Rate limit reached. Waiting {wait_time:.2f} seconds.")
                    time.sleep(wait_time)

    def _save_response(self, response: LLMResponse, filepath: str) -> None:
        """
        Save LLM response to a file.
        
        Args:
            response: Response to save
            filepath: Path to save the response
        """
        data = {
            'content': response.content,
            'tokens_used': response.tokens_used,
            'model': response.model,
            'provider': response.provider,
            'metadata': response.metadata,
            'timestamp': response.timestamp
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def _load_response(cls, filepath: str) -> LLMResponse:
        """
        Load LLM response from a file.
        
        Args:
            filepath: Path to load the response from
            
        Returns:
            LLMResponse object
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        return LLMResponse(**data)

    def __enter__(self):
        """Context manager entry."""
        self._validate_parameters()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass

class GPT4Client(LLMClient):
    """Client for OpenAI's GPT-4 model."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from openai import OpenAI
        
        self.client = OpenAI(api_key=self.api_key)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """Generate text using GPT-4."""
        self._handle_rate_limit()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.chat.completions.create(model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            frequency_penalty=self.frequency_penalty,
            presence_penalty=self.presence_penalty,
            stop=self.stop,
            **kwargs)

            return LLMResponse(
                content=response.choices[0].message.content,
                tokens_used=response.usage.total_tokens,
                model=self.model,
                provider="openai",
                metadata={
                    'finish_reason': response.choices[0].finish_reason,
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens
                }
            )

        except Exception as e:
            logger.error(f"Error generating text with GPT-4: {e}")
            raise

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken."""
        import tiktoken
        encoding = tiktoken.encoding_for_model(self.model)
        return len(encoding.encode(text))

    def get_available_models(self) -> List[str]:
        """Get available GPT-4 models."""
        return [
            "gpt-4",
            "gpt-4-32k",
            "gpt-4-turbo-preview"
        ]

def create_llm_client(
    provider: str,
    api_key: str,
    model: str,
    **kwargs
) -> LLMClient:
    """
    Factory function to create LLM clients.
    
    Args:
        provider: LLM provider name
        api_key: API key for the provider
        model: Model name to use
        **kwargs: Additional client parameters
        
    Returns:
        LLMClient instance
        
    Raises:
        ValueError: If provider is not supported
    """
    providers = {
        'gpt4': GPT4Client,
        # Add more providers here
    }

    if provider.lower() not in providers:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    return providers[provider.lower()](api_key=api_key, model=model, **kwargs) 