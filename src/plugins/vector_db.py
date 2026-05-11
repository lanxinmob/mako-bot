from typing import List

from nonebot.log import logger

from src.services.vector_store import VectorStore


_vector_store = VectorStore()


def create_db():
    if not _vector_store.redis:
        return
    try:
        _vector_store.ensure_index()
    except Exception as exc:
        logger.warning(f"向量索引初始化失败，已跳过长期记忆检索: {exc}")

def add_to_db(point_text:str):
    if not point_text:
        return
    if not _vector_store.redis:
        logger.warning("Redis 不可用，跳过长期记忆写入。")
        return
    try:
        _vector_store.add(point_text)
    except Exception as exc:
        logger.warning(f"长期记忆写入失败，已跳过: {exc}")

def search_db(query: str,top_k: int = 3,score_threshold=0.4) -> List[str]:
    if not query.strip() or not _vector_store.redis:
        return []
    try:
        return _vector_store.search(query, top_k=top_k, score_threshold=score_threshold)
    except Exception as exc:
        logger.warning(f"长期记忆检索失败，已返回空结果: {exc}")
        return []
