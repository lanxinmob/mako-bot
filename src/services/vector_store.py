from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import List

import numpy as np
from nonebot.log import logger
from redis.commands.search.field import TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from sentence_transformers import SentenceTransformer

from src.core.config import get_settings
from src.services.redis import get_redis


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    logger.info(f"Loading embedding model: {settings.embedding_model}")
    return SentenceTransformer(settings.embedding_model)


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.redis = get_redis()
        self.index_name = self.settings.vector_index_name
        self.prefix = self.settings.vector_prefix

    @property
    def dimension(self) -> int:
        return get_embedding_model().get_sentence_embedding_dimension()

    def ensure_index(self) -> None:
        if not self.redis:
            return
        fields = [
            TextField("point_text"),
            VectorField(
                "vector",
                "HNSW",
                {"TYPE": "FLOAT32", "DIM": self.dimension, "DISTANCE_METRIC": "COSINE"},
            ),
        ]
        try:
            self.redis.ft(self.index_name).info()
        except Exception:
            logger.warning(f"Vector index {self.index_name} missing, creating.")
            self.redis.ft(self.index_name).create_index(
                fields=fields,
                definition=IndexDefinition(prefix=[self.prefix], index_type=IndexType.HASH),
            )
            logger.success(f"Vector index {self.index_name} created.")

    def add(self, text: str) -> None:
        if not self.redis:
            return
        self.ensure_index()
        item_id = hashlib.md5(text.encode("utf-8")).hexdigest()
        key = f"{self.prefix}{item_id}"
        vector = get_embedding_model().encode(text).astype(np.float32).tobytes()
        self.redis.hset(key, mapping={"point_text": text, "vector": vector})
        logger.success(f"Stored memory point: {text[:50]}")

    def search(self, query_text: str, top_k: int = 3, score_threshold: float = 0.4) -> List[str]:
        if not self.redis:
            return []
        self.ensure_index()
        query_vector = get_embedding_model().encode(query_text).astype(np.float32).tobytes()
        query = (
            Query(f"(*)=>[KNN {top_k} @vector $query_vector AS score]")
            .sort_by("score")
            .return_fields("point_text", "score")
            .dialect(2)
        )
        params = {"query_vector": query_vector}
        results = self.redis.ft(self.index_name).search(query, params).docs
        filtered: List[str] = []
        for doc in results:
            if float(doc.score) < score_threshold:
                filtered.append(doc.point_text)
        return filtered
