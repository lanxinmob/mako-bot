"""Default adapters; the R14 compatibility entry can inject its own module."""
from __future__ import annotations
import asyncio
import re
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, List, Optional
from urllib.parse import urlsplit
from nonebot.log import logger
from src.core.config import get_settings
from src.services.chat.policy import compact_text
from src.services.integrations.image import describe_image_url
from src.services.tools.intent import decide_intents
from src.services.tools.intent import is_correction_request
from src.services.tools.intent import is_dynamic_fact_query
from src.services.integrations.llm import get_deepseek_client
from src.services.integrations.llm import get_deepseek_model
from src.services.integrations.llm import has_deepseek
from src.services.delivery.reminder import extract_json_object
from src.services.retrieval.client import SearchResult
from src.services.retrieval.client import fetch_page_text
from src.services.retrieval.client import web_search
from src.services.retrieval.metrics import search_metrics
