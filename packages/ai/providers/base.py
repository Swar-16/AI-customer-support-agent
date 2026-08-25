from abc import ABC, abstractmethod
from typing import TypeVar, Type

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...
    
    @abstractmethod
    def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model: Type[T]) -> T:
        ...
    
    @abstractmethod
    def health_check(self) -> bool:
        ...