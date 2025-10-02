import redis
import numpy as np
from sentence_transformers import SentenceTransformer
from redis.commands.search.field import VectorField, TextField
from redis.commands.search.query import Query
import hashlib
from nonebot.log import logger

print("加载模型")
embedding_model = SentenceTransformer("moka-ai/m3e-base")
VECTOR_DIMENSION = embedding_model.get_sentence_embedding_dimension()
print(f"加载完成，向量维度：{VECTOR_DIMENSION}")

try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping() 
    logger.success("成功连接到Redis，聊天记录将持久化！")
except redis.exceptions.ConnectionError as e:
    logger.error(f"连接Redis失败！将使用内存模式。错误: {e}")
    redis_client = None 

INDEX_NAME = "Long_term_memory"
PREFIX = "memory "
def create_db():
    content = {TextField("point_text"),
               VectorField("vector","HNSW",{"TYPE":"FLOAT32","DIM":VECTOR_DIMENSION,"DISTANCE_METRIC":"COSINE"})
               }
    try:
        redis_client.ft(INDEX_NAME).info()
    except redis.exceptions.ResponseError():
        logger.error(f"索引{INDEX_NAME}不存在，正在创建")
        redis_client.ft(INDEX_NAME).create_index(fields=content,
                                                 definition=redis.commands.search.document.DocumentDefiniton(prefix=[PREFIX]))
        logger.success(f"索引{INDEX_NAME}创建成功")

def add_to_db(point_text:str):
    id = hashlib.md5(point_text.encode()).hexdigest()
    key = f"{PREFIX}{id}"
    vector = embedding_model.encode(point_text).astype(np.float32).tobytes()
    redis_client.hset(key,mapping={"point_text":point_text,"vector":vector})
    logger.success(f"记忆{point_text}已存入Redis")

def search_db(query: str,top_k: int = 3,score_threshold=0.4):
    query_vecotr = embedding_model.encode(query).astype(np.float32).tobytes()
    q = Query(f"(*)=>[KNN {top_k} @vector $query_vector AS score]").sort_by("score").return_fields("point_text","score").dialect(2)
    params = {"query_vector":query_vecotr}
    results = redis_client.ft(INDEX_NAME).search(q,params).docs
    filtered = []
    for doc in results:
        if float(doc.score) < score_threshold:
            filtered.append(doc.point_text)
    return filtered