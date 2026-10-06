"""Explicit adapter dependencies; no connections are opened here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.services.integrations.amap import geocode
from src.services.integrations.amap import plan_route
from src.services.integrations.amap import search_poi
from src.services.integrations.emoji import analyze_emoji
from src.services.integrations.image import describe_image_url
from src.services.integrations.image import download_image_bytes
from src.services.integrations.image import generate_image
from src.services.integrations.image import process_image
from src.services.integrations.language import detect_language
from src.services.integrations.language import speech_to_text
from src.services.integrations.language import text_to_speech
from src.services.integrations.language import translate_text
from src.services.integrations.llm import get_deepseek_client
from src.services.integrations.llm import get_deepseek_model
from src.services.integrations.llm import get_openai_client
from src.services.integrations.llm import has_deepseek
from src.services.integrations.llm import has_openai
from src.services.retrieval.client import fetch_page_text
from src.services.retrieval.client import web_search
from src.services.integrations.weather import get_weather


@dataclass
class ToolDependencies:
    describe_image_url: Callable = describe_image_url
    download_image_bytes: Callable = download_image_bytes
    generate_image: Callable = generate_image
    process_image: Callable = process_image
    detect_language: Callable = detect_language
    speech_to_text: Callable = speech_to_text
    text_to_speech: Callable = text_to_speech
    translate_text: Callable = translate_text
    get_deepseek_client: Callable = get_deepseek_client
    get_deepseek_model: Callable = get_deepseek_model
    get_openai_client: Callable = get_openai_client
    has_deepseek: Callable = has_deepseek
    has_openai: Callable = has_openai
    fetch_page_text: Callable = fetch_page_text
    web_search: Callable = web_search
    geocode: Callable = geocode
    plan_route: Callable = plan_route
    search_poi: Callable = search_poi
    get_weather: Callable = get_weather
    analyze_emoji: Callable = analyze_emoji
