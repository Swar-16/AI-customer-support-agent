from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from packages.knowledge.embeddings.models import (
    EmbeddingProviderDescriptor,
    EmbeddingVector,
)
from packages.knowledge.embeddings.provider.query_cache import (
    QueryEmbeddingCache,
)


@pytest.fixture
def descriptor() -> EmbeddingProviderDescriptor:
    return EmbeddingProviderDescriptor(
        provider="test",
        model="test-model",
        revision="v1",
        dimensions=3,
    )


def make_vector() -> EmbeddingVector:
    return EmbeddingVector(values=(0.1, 0.2, 0.3))


def test_reuses_cached_query_embedding(descriptor) -> None:
    cache = QueryEmbeddingCache(max_entries=8, ttl_seconds=60)
    calls = 0

    def loader() -> EmbeddingVector:
        nonlocal calls
        calls += 1
        return make_vector()

    first = cache.get_or_compute(
        text="Where is my order?",
        descriptor=descriptor,
        loader=loader,
    )
    second = cache.get_or_compute(
        text="Where is my order?",
        descriptor=descriptor,
        loader=loader,
    )

    assert calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.vector == second.vector


def test_different_query_does_not_collide(descriptor) -> None:
    cache = QueryEmbeddingCache(max_entries=8, ttl_seconds=60)
    calls = 0

    def loader() -> EmbeddingVector:
        nonlocal calls
        calls += 1
        return make_vector()

    cache.get_or_compute(
        text="Where is my order?",
        descriptor=descriptor,
        loader=loader,
    )
    cache.get_or_compute(
        text="How do I request a refund?",
        descriptor=descriptor,
        loader=loader,
    )

    assert calls == 2


def test_different_provider_descriptor_does_not_collide(
    descriptor,
) -> None:
    cache = QueryEmbeddingCache(max_entries=8, ttl_seconds=60)
    calls = 0

    other_descriptor = EmbeddingProviderDescriptor(
        provider="test",
        model="other-model",
        revision="v1",
        dimensions=3,
    )

    def loader() -> EmbeddingVector:
        nonlocal calls
        calls += 1
        return make_vector()

    cache.get_or_compute(
        text="Where is my order?",
        descriptor=descriptor,
        loader=loader,
    )
    cache.get_or_compute(
        text="Where is my order?",
        descriptor=other_descriptor,
        loader=loader,
    )

    assert calls == 2


def test_failure_is_not_cached(descriptor) -> None:
    cache = QueryEmbeddingCache(max_entries=8, ttl_seconds=60)
    calls = 0

    def failing_loader() -> EmbeddingVector:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError, match="provider failed"):
        cache.get_or_compute(
            text="Where is my order?",
            descriptor=descriptor,
            loader=failing_loader,
        )

    with pytest.raises(RuntimeError, match="provider failed"):
        cache.get_or_compute(
            text="Where is my order?",
            descriptor=descriptor,
            loader=failing_loader,
        )

    assert calls == 2


def test_lru_capacity_is_bounded(descriptor) -> None:
    cache = QueryEmbeddingCache(max_entries=2, ttl_seconds=60)
    calls = 0

    def loader() -> EmbeddingVector:
        nonlocal calls
        calls += 1
        return make_vector()

    for query in ("one", "two", "three"):
        cache.get_or_compute(
            text=query,
            descriptor=descriptor,
            loader=loader,
        )

    assert cache.size == 2
    assert cache.evictions == 1

    cache.get_or_compute(
        text="one",
        descriptor=descriptor,
        loader=loader,
    )

    assert calls == 4


def test_single_flight_collapses_simultaneous_requests(
    descriptor,
) -> None:
    cache = QueryEmbeddingCache(max_entries=8, ttl_seconds=60)

    loader_started = Event()
    allow_loader_to_finish = Event()
    count_lock = Lock()
    calls = 0

    def loader() -> EmbeddingVector:
        nonlocal calls

        with count_lock:
            calls += 1

        loader_started.set()
        assert allow_loader_to_finish.wait(timeout=2)
        return make_vector()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            cache.get_or_compute,
            text="same query",
            descriptor=descriptor,
            loader=loader,
        )

        assert loader_started.wait(timeout=2)

        second_future = executor.submit(
            cache.get_or_compute,
            text="same query",
            descriptor=descriptor,
            loader=loader,
        )

        allow_loader_to_finish.set()

        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert calls == 1
    assert first.vector == second.vector
    assert sorted(
        [first.cache_hit, second.cache_hit]
    ) == [False, True]