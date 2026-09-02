from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json


@dataclass(frozen=True, slots=True)
class RetrievalProfile:
    """
    Configuration controlling one retrieval pipeline execution.

    This object contains retrieval behavior only. Provider-specific and persistence-specific configuration belongs elsewhere.
    """
    profile_id: str
    vector_enabled: bool = True
    lexical_enabled: bool = True
    reranking_enabled: bool = False
    vector_candidate_limit: int = 20
    lexical_candidate_limit: int = 20
    fused_candidate_limit: int = 20
    final_candidate_limit: int = 8
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str):
            raise TypeError("profile_id must be a string.")

        normalized_profile_id = self.profile_id.strip().lower()

        if not normalized_profile_id:
            raise ValueError("profile_id cannot be blank.")

        object.__setattr__(self, "profile_id", normalized_profile_id)

        for field_name in ("vector_enabled", "lexical_enabled", "reranking_enabled",):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a boolean.")

        if not self.vector_enabled and not self.lexical_enabled:
            raise ValueError("At least one retrieval mechanism must be enabled.")

        for field_name in ("vector_candidate_limit", "lexical_candidate_limit", "fused_candidate_limit", "final_candidate_limit", "rrf_k",):
            self._validate_positive_integer(field_name, getattr(self, field_name))

        if self.vector_enabled and not self.lexical_enabled and self.fused_candidate_limit > self.vector_candidate_limit:
                    raise ValueError("fused_candidate_limit cannot exceed vector_candidate_limit when only vector retrieval is enabled.")

        if self.lexical_enabled and not self.vector_enabled and self.fused_candidate_limit > self.lexical_candidate_limit:
                    raise ValueError("fused_candidate_limit cannot exceed lexical_candidate_limit when only lexical retrieval is enabled.")

        if self.vector_enabled and self.fused_candidate_limit > (self.vector_candidate_limit + self.lexical_candidate_limit):
            raise ValueError("fused_candidate_limit cannot exceed the maximum number of candidates available from enabled retrievers.")

        if self.final_candidate_limit > self.fused_candidate_limit:
            raise ValueError("final_candidate_limit cannot exceed fused_candidate_limit.")

    @staticmethod
    def _validate_positive_integer(field_name: str, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer.")

        if value <= 0:
            raise ValueError(f"{field_name} must be greater than zero.")

    @property
    def config_fingerprint(self) -> str:
        """
        Stable fingerprint representing behavior-affecting profile settings.

        Useful later for telemetry and reproducibility.
        """
        payload = {
            "profile_id": self.profile_id,
            "vector_enabled": self.vector_enabled,
            "lexical_enabled": self.lexical_enabled,
            "reranking_enabled": self.reranking_enabled,
            "vector_candidate_limit": self.vector_candidate_limit,
            "lexical_candidate_limit": self.lexical_candidate_limit,
            "fused_candidate_limit": self.fused_candidate_limit,
            "final_candidate_limit": self.final_candidate_limit,
            "rrf_k": self.rrf_k,
        }

        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )

        return sha256(serialized.encode("utf-8")).hexdigest()

    @property
    def identity(self) -> str:
        return f"{self.profile_id}:{self.config_fingerprint}"
    
def create_default_customer_support_profile() -> RetrievalProfile:
    """
    Create the default retrieval configuration used for customer-support RAG.

    A factory is used instead of a process-global instance so composition receives a fresh immutable profile object each time.
    """
    return RetrievalProfile(
        profile_id="customer-support-default",
        vector_enabled=True,
        lexical_enabled=True,
        reranking_enabled=False,
        vector_candidate_limit=20,
        lexical_candidate_limit=20,
        fused_candidate_limit=20,
        final_candidate_limit=8,
        rrf_k=60,
    )