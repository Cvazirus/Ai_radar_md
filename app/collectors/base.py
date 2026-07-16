from abc import ABC, abstractmethod
from typing import List
from app.collectors.schemas import CollectedItem

class BaseCollector(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def source_type(self) -> str:
        pass

    @abstractmethod
    def collect(self) -> List[CollectedItem]:
        pass
