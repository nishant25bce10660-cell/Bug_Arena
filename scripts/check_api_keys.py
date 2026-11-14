"""Live API connectivity and key verification script for BugArena."""

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

# Add src to sys.path and load .env
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from bugarena.config import load_env_file

load_env_file()


async def check_gemini() -> dict:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return {"provider": "Google Gemini", "status": "KEY_NOT_FOUND", "message": "GEMINI_API_KEY is not set."}

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemma-4-26b-a4b-it:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    payload = {"contents": [{"role": "user", "parts": [{"text": "Hello"}]}], "generationConfig": {"maxOutputTokens": 5}}

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            elapsed = time.perf_counter() - start
            if resp.status_code == 200:
                return {
                    "provider": "Google Gemini (gemma-4-26b-a4b-it)",
                    "status": "ONLINE",
                    "latency": f"{elapsed:.2f}s",
                    "message": "Authenticated and responding successfully.",
                }
            else:
                return {
                    "provider": "Google Gemini",
                    "status": "ERROR",
                    "code": resp.status_code,
                    "message": resp.text[:120],
                }
    except (httpx.HTTPError, OSError) as exc:
        return {"provider": "Google Gemini", "status": "NETWORK_ERROR", "message": str(exc)}


async def check_openai() -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return {"provider": "OpenAI", "status": "KEY_NOT_FOUND", "message": "OPENAI_API_KEY is not set."}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 5}

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            elapsed = time.perf_counter() - start
            if resp.status_code == 200:
                return {
                    "provider": "OpenAI (gpt-4o-mini)",
                    "status": "ONLINE",
                    "latency": f"{elapsed:.2f}s",
                    "message": "Authenticated and responding successfully.",
                }
            else:
                return {
                    "provider": "OpenAI",
                    "status": "ERROR",
                    "code": resp.status_code,
                    "message": resp.text[:120],
                }
    except (httpx.HTTPError, OSError) as exc:
        return {"provider": "OpenAI", "status": "NETWORK_ERROR", "message": str(exc)}


async def check_deepseek() -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return {"provider": "DeepSeek", "status": "KEY_NOT_FOUND", "message": "DEEPSEEK_API_KEY is not set."}

    url = "https://api.deepseek.com/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 5}

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            elapsed = time.perf_counter() - start
            if resp.status_code == 200:
                return {
                    "provider": "DeepSeek (deepseek-chat)",
                    "status": "ONLINE",
                    "latency": f"{elapsed:.2f}s",
                    "message": "Authenticated and responding successfully.",
                }
            else:
                return {
                    "provider": "DeepSeek",
                    "status": "ERROR",
                    "code": resp.status_code,
                    "message": resp.text[:120],
                }
    except (httpx.HTTPError, OSError) as exc:
        return {"provider": "DeepSeek", "status": "NETWORK_ERROR", "message": str(exc)}


async def check_groq() -> dict:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return {"provider": "Groq", "status": "KEY_NOT_FOUND", "message": "GROQ_API_KEY is not set."}

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen/qwen3.8-27b",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 5,
    }

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            elapsed = time.perf_counter() - start
            if resp.status_code == 200:
                return {
                    "provider": "Groq (qwen/qwen3.8-27b)",
                    "status": "ONLINE",
                    "latency": f"{elapsed:.2f}s",
                    "message": "Authenticated and responding successfully.",
                }
            else:
                return {
                    "provider": "Groq",
                    "status": "ERROR",
                    "code": resp.status_code,
                    "message": resp.text[:120],
                }
    except (httpx.HTTPError, OSError) as exc:
        return {"provider": "Groq", "status": "NETWORK_ERROR", "message": str(exc)}


async def check_ollama() -> dict:
    url = "http://localhost:11434/api/tags"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                models = [m.get("name") for m in resp.json().get("models", [])]
                return {
                    "provider": "Local Ollama",
                    "status": "ONLINE",
                    "message": f"Connected. Installed models: {models[:3]}",
                }
    except (httpx.HTTPError, OSError):
        return {"provider": "Local Ollama", "status": "OFFLINE", "message": "Not running on localhost:11434."}
    return {"provider": "Local Ollama", "status": "OFFLINE", "message": "Not running on localhost:11434."}


async def main():
    print("\n=======================================================")
    print("        BugArena Multi-Agent API Status Check          ")
    print("=======================================================\n")

    results = await asyncio.gather(
        check_gemini(),
        check_openai(),
        check_deepseek(),
        check_groq(),
        check_ollama(),
    )

    for r in results:
        status = r["status"]
        provider = r["provider"]
        msg = r["message"]
        latency = f" ({r['latency']})" if "latency" in r else ""

        if status == "ONLINE":
            print(f" [ONLINE]  {provider}{latency} -> {msg}")
        elif status == "KEY_NOT_FOUND":
            print(f" [WAITING] {provider} -> {msg}")
        elif status == "OFFLINE":
            print(f" [OFFLINE] {provider} -> {msg}")
        else:
            print(f" [ERROR]   {provider} -> {msg}")

    print("\n-------------------------------------------------------")
    print("To activate any provider, add your key to `.env` or:")
    print("C:\\Users\\nisha\\.gemini\\config\\mcp_config.json")
    print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())
