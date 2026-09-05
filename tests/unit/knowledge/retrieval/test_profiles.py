from __future__ import annotations

import re

import pytest

from packages.knowledge.retrieval.profiles import (
    RetrievalProfile,
    create_default_customer_support_profile,
)


class TestRetrievalProfile:
    def test_constructs_valid_profile(self) -> None:
        profile = RetrievalProfile(
            profile_id="customer-support",
            vector_enabled=True,
            lexical_enabled=True,
            reranking_enabled=False,
            vector_candidate_limit=20,
            lexical_candidate_limit=20,
            fused_candidate_limit=20,
            final_candidate_limit=8,
            rrf_k=60,
        )

        assert profile.profile_id == "customer-support"
        assert profile.vector_enabled is True
        assert profile.lexical_enabled is True
        assert profile.reranking_enabled is False

        assert profile.vector_candidate_limit == 20
        assert profile.lexical_candidate_limit == 20
        assert profile.fused_candidate_limit == 20
        assert profile.final_candidate_limit == 8
        assert profile.rrf_k == 60

    def test_profile_id_is_normalized(self) -> None:
        profile = RetrievalProfile(
            profile_id="  CUSTOMER-SUPPORT  ",
        )

        assert profile.profile_id == "customer-support"

    def test_profile_id_must_be_string(self) -> None:
        with pytest.raises(
            TypeError,
            match="profile_id must be a string",
        ):
            RetrievalProfile(
                profile_id=123,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "profile_id",
        [
            "",
            " ",
            "\n\t",
        ],
    )
    def test_profile_id_cannot_be_blank(
        self,
        profile_id: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="profile_id cannot be blank",
        ):
            RetrievalProfile(
                profile_id=profile_id,
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "vector_enabled",
            "lexical_enabled",
            "reranking_enabled",
        ],
    )
    def test_boolean_configuration_fields_must_be_boolean(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            field_name: 1,
        }

        with pytest.raises(
            TypeError,
            match=f"{field_name} must be a boolean",
        ):
            RetrievalProfile(
                profile_id="test-profile",
                **kwargs,  # type: ignore[arg-type]
            )

    def test_requires_at_least_one_retrieval_mechanism(self) -> None:
        with pytest.raises(
            ValueError,
            match="At least one retrieval mechanism must be enabled",
        ):
            RetrievalProfile(
                profile_id="invalid",
                vector_enabled=False,
                lexical_enabled=False,
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "vector_candidate_limit",
            "lexical_candidate_limit",
            "fused_candidate_limit",
            "final_candidate_limit",
            "rrf_k",
        ],
    )
    def test_integer_configuration_fields_must_be_integer(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            field_name: 1.5,
        }

        with pytest.raises(
            TypeError,
            match=f"{field_name} must be an integer",
        ):
            RetrievalProfile(
                profile_id="test-profile",
                **kwargs,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "vector_candidate_limit",
            "lexical_candidate_limit",
            "fused_candidate_limit",
            "final_candidate_limit",
            "rrf_k",
        ],
    )
    def test_integer_configuration_fields_reject_boolean(
        self,
        field_name: str,
    ) -> None:
        kwargs = {
            field_name: True,
        }

        with pytest.raises(
            TypeError,
            match=f"{field_name} must be an integer",
        ):
            RetrievalProfile(
                profile_id="test-profile",
                **kwargs,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "value",
        [
            0,
            -1,
            -100,
        ],
    )
    @pytest.mark.parametrize(
        "field_name",
        [
            "vector_candidate_limit",
            "lexical_candidate_limit",
            "fused_candidate_limit",
            "final_candidate_limit",
            "rrf_k",
        ],
    )
    def test_integer_configuration_fields_must_be_positive(
        self,
        field_name: str,
        value: int,
    ) -> None:
        kwargs = {
            field_name: value,
        }

        with pytest.raises(
            ValueError,
            match=f"{field_name} must be greater than zero",
        ):
            RetrievalProfile(
                profile_id="test-profile",
                **kwargs,
            )

    def test_final_candidate_limit_cannot_exceed_fused_limit(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "final_candidate_limit cannot exceed "
                "fused_candidate_limit"
            ),
        ):
            RetrievalProfile(
                profile_id="invalid",
                fused_candidate_limit=5,
                final_candidate_limit=6,
            )

    def test_vector_only_profile_is_valid(self) -> None:
        profile = RetrievalProfile(
            profile_id="vector-only",
            vector_enabled=True,
            lexical_enabled=False,
            vector_candidate_limit=20,
            lexical_candidate_limit=20,
            fused_candidate_limit=10,
            final_candidate_limit=5,
        )

        assert profile.vector_enabled is True
        assert profile.lexical_enabled is False

    def test_vector_only_fused_limit_cannot_exceed_vector_limit(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "fused_candidate_limit cannot exceed "
                "vector_candidate_limit"
            ),
        ):
            RetrievalProfile(
                profile_id="vector-only",
                vector_enabled=True,
                lexical_enabled=False,
                vector_candidate_limit=10,
                fused_candidate_limit=11,
                final_candidate_limit=5,
            )

    def test_lexical_only_profile_is_valid(self) -> None:
        profile = RetrievalProfile(
            profile_id="lexical-only",
            vector_enabled=False,
            lexical_enabled=True,
            vector_candidate_limit=20,
            lexical_candidate_limit=20,
            fused_candidate_limit=10,
            final_candidate_limit=5,
        )

        assert profile.vector_enabled is False
        assert profile.lexical_enabled is True

    def test_lexical_only_fused_limit_cannot_exceed_lexical_limit(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "fused_candidate_limit cannot exceed "
                "lexical_candidate_limit"
            ),
        ):
            RetrievalProfile(
                profile_id="lexical-only",
                vector_enabled=False,
                lexical_enabled=True,
                lexical_candidate_limit=10,
                fused_candidate_limit=11,
                final_candidate_limit=5,
            )

    def test_hybrid_fused_limit_may_use_candidates_from_both_retrievers(
        self,
    ) -> None:
        profile = RetrievalProfile(
            profile_id="hybrid",
            vector_enabled=True,
            lexical_enabled=True,
            vector_candidate_limit=10,
            lexical_candidate_limit=10,
            fused_candidate_limit=15,
            final_candidate_limit=8,
        )

        assert profile.fused_candidate_limit == 15

    def test_hybrid_fused_limit_cannot_exceed_total_available_candidates(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "fused_candidate_limit cannot exceed the maximum "
                "number of candidates available"
            ),
        ):
            RetrievalProfile(
                profile_id="hybrid",
                vector_enabled=True,
                lexical_enabled=True,
                vector_candidate_limit=10,
                lexical_candidate_limit=10,
                fused_candidate_limit=21,
                final_candidate_limit=8,
            )


class TestRetrievalProfileFingerprint:
    def test_config_fingerprint_is_sha256_hex(self) -> None:
        profile = RetrievalProfile(
            profile_id="customer-support",
        )

        fingerprint = profile.config_fingerprint

        assert len(fingerprint) == 64
        assert re.fullmatch(
            r"[0-9a-f]{64}",
            fingerprint,
        )

    def test_fingerprint_is_deterministic(self) -> None:
        first = RetrievalProfile(
            profile_id="customer-support",
            vector_candidate_limit=30,
            lexical_candidate_limit=25,
            fused_candidate_limit=20,
            final_candidate_limit=8,
            rrf_k=60,
        )

        second = RetrievalProfile(
            profile_id="customer-support",
            vector_candidate_limit=30,
            lexical_candidate_limit=25,
            fused_candidate_limit=20,
            final_candidate_limit=8,
            rrf_k=60,
        )

        assert (
            first.config_fingerprint
            == second.config_fingerprint
        )

    def test_profile_id_normalization_does_not_change_fingerprint(
        self,
    ) -> None:
        first = RetrievalProfile(
            profile_id="CUSTOMER-SUPPORT",
        )

        second = RetrievalProfile(
            profile_id="  customer-support  ",
        )

        assert first.config_fingerprint == second.config_fingerprint

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("vector_enabled", False),
            ("lexical_enabled", False),
            ("reranking_enabled", True),
            ("vector_candidate_limit", 25),
            ("lexical_candidate_limit", 25),
            ("fused_candidate_limit", 15),
            ("final_candidate_limit", 6),
            ("rrf_k", 40),
        ],
    )
    def test_behavior_affecting_configuration_changes_fingerprint(
        self,
        field_name: str,
        value: object,
    ) -> None:
        baseline = RetrievalProfile(
            profile_id="baseline",
        )

        kwargs = {
            field_name: value,
        }

        changed = RetrievalProfile(
            profile_id="baseline",
            **kwargs,  # type: ignore[arg-type]
        )

        assert (
            baseline.config_fingerprint
            != changed.config_fingerprint
        )

    def test_profile_id_changes_fingerprint(self) -> None:
        first = RetrievalProfile(
            profile_id="profile-a",
        )

        second = RetrievalProfile(
            profile_id="profile-b",
        )

        assert (
            first.config_fingerprint
            != second.config_fingerprint
        )

    def test_identity_contains_normalized_profile_and_fingerprint(
        self,
    ) -> None:
        profile = RetrievalProfile(
            profile_id="  CUSTOMER-SUPPORT  ",
        )

        assert profile.identity == (
            f"customer-support:{profile.config_fingerprint}"
        )


class TestDefaultCustomerSupportProfile:
    def test_factory_returns_expected_profile(self) -> None:
        profile = create_default_customer_support_profile()

        assert profile.profile_id == "customer-support-default"

        assert profile.vector_enabled is True
        assert profile.lexical_enabled is True
        assert profile.reranking_enabled is False

        assert profile.vector_candidate_limit == 20
        assert profile.lexical_candidate_limit == 20
        assert profile.fused_candidate_limit == 20
        assert profile.final_candidate_limit == 8

        assert profile.rrf_k == 60

    def test_factory_returns_new_instance_each_time(self) -> None:
        first = create_default_customer_support_profile()
        second = create_default_customer_support_profile()

        assert first == second
        assert first is not second

    def test_default_profile_has_stable_identity(self) -> None:
        first = create_default_customer_support_profile()
        second = create_default_customer_support_profile()

        assert first.identity == second.identity