"""Multi-model API dispatcher connecting competing personas to Gemini, OpenAI, DeepSeek, Groq, and Ollama."""

import os
import re

import httpx

from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.personas.base import get_persona_prompt

DIFF_BLOCK_REGEX = re.compile(
    r"```(?:diff)?\n(--- (?:a/)?\S+\n\+\+\+ (?:b/)?\S+\n[\s\S]+?)```", re.MULTILINE
)
RAW_DIFF_REGEX = re.compile(r"(--- (?:a/)?\S+\n\+\+\+ (?:b/)?\S+\n@@[\s\S]+)", re.MULTILINE)


def get_recommended_model_for_persona(persona: PersonaType) -> str:
    """
    Return the optimal model for a specific repair persona based on available keys.
    Prioritizes active keys (Groq, Gemini, OpenAI, DeepSeek); no Claude key required.
    """
    has_groq = bool(os.environ.get("GROQ_API_KEY"))
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_deepseek = bool(os.environ.get("DEEPSEEK_API_KEY"))

    if persona == PersonaType.SURGICAL_MINIMALIST:
        if has_groq:
            return "qwen/qwen3.8-27b"
        if has_gemini:
            return "gemma-4-26b-a4b-it"
        if has_openai:
            return "gpt-4o-mini"
        if has_deepseek:
            return "deepseek-chat"
        return "qwen/qwen3.8-27b"

    if persona == PersonaType.DEFENSIVE_GUARDIAN:
        if has_gemini:
            return "gemma-4-26b-a4b-it"
        if has_groq:
            return "qwen/qwen3.8-27b"
        if has_openai:
            return "gpt-4o"
        return "gemma-4-26b-a4b-it"

    if persona == PersonaType.ARCHITECTURAL_FIXER:
        if has_groq:
            return "qwen/qwen3.8-27b"
        if has_gemini:
            return "gemma-4-26b-a4b-it"
        if has_openai:
            return "o3-mini"
        if has_deepseek:
            return "deepseek-reasoner"
        return "qwen/qwen3.8-27b"

    if persona == PersonaType.CONTRACT_ENFORCER:
        if has_gemini:
            return "gemma-4-26b-a4b-it"
        if has_groq:
            return "qwen/qwen3.8-27b"
        if has_deepseek:
            return "deepseek-reasoner"
        if has_openai:
            return "gpt-4o"
        return "gemma-4-26b-a4b-it"

    return "qwen/qwen3.8-27b"


def extract_diff_and_explanation(response_text: str) -> tuple[str, str]:
    """
    Extract a unified diff and explanatory commentary from an LLM response.
    """
    clean_text = response_text.strip()
    match = DIFF_BLOCK_REGEX.search(clean_text)
    if match:
        diff = match.group(1).strip()
        explanation = clean_text[: match.start()].strip() + " " + clean_text[match.end() :].strip()
        return diff, explanation.strip()

    raw_match = RAW_DIFF_REGEX.search(clean_text)
    if raw_match:
        diff = raw_match.group(1).strip()
        explanation = clean_text[: raw_match.start()].strip()
        return diff, explanation.strip()

    return "", clean_text


def build_repair_prompt(
    persona: PersonaType,
    bug_spec: BugSpec,
    repro_spec: ReproTestSpec,
) -> str:
    """
    Construct a structured repair prompt for an LLM agent persona.
    """
    persona_directive = get_persona_prompt(persona)
    primary_suspect = bug_spec.suspects[0] if bug_spec.suspects else None

    suspect_info = ""
    if primary_suspect:
        suspect_info = (
            f"Target file: `{primary_suspect.file_path}`\n"
            f"Suspected lines: {primary_suspect.line_range[0]} to {primary_suspect.line_range[1]}\n"
            f"Code snippet:\n```python\n{primary_suspect.code_snippet}\n```\n"
            f"Fault diagnosis: {primary_suspect.reasoning}\n"
        )

    prompt = f"""# Persona Directive
{persona_directive}

# Bug Report
Error Log / Trace:
```
{bug_spec.error_log or "No raw trace available."}
```
Hint: {bug_spec.hint or "None"}

{suspect_info}
# Failing Reproduction Test
A reproduction test case has been created that currently FAILS on the codebase.
Test path: `{repro_spec.test_file_path}`
Test code:
```python
{repro_spec.test_code}
```

# Instructions
1. Analyze the root cause based on your persona directive.
2. Produce a fix that turns the reproduction test from Red to Green without breaking regressions.
3. You MUST output your fix as a git-compatible unified diff enclosed within ```diff ``` markers:
```diff
--- a/{primary_suspect.file_path if primary_suspect else "src/main.py"}
+++ b/{primary_suspect.file_path if primary_suspect else "src/main.py"}
@@ -line,count +line,count @@
...
```
"""
    return prompt


class MultiModelDispatcher:
    """Dispatches repair prompts across Gemini, OpenAI, DeepSeek, Groq, or Ollama."""

    def __init__(self, timeout_seconds: float = 60.0):
        self.timeout_seconds = timeout_seconds

    async def generate_patch(
        self,
        persona: PersonaType,
        bug_spec: BugSpec,
        repro_spec: ReproTestSpec,
        model_override: str | None = None,
    ) -> tuple[str, str]:
        """
        Query the appropriate LLM provider for a candidate patch.
        Gracefully routes to available API keys without requiring Claude.
        """
        model = model_override or get_recommended_model_for_persona(persona)
        prompt = build_repair_prompt(persona, bug_spec, repro_spec)
        system_msg = get_persona_prompt(persona)

        # Fallback if Claude is requested without a key
        if "claude" in model.lower() and not os.environ.get("ANTHROPIC_API_KEY"):
            model = get_recommended_model_for_persona(persona)

        # Route by model identifier
        if "gemini" in model.lower() or "gemma" in model.lower():
            return await self._call_gemini(model, system_msg, prompt)
        elif "deepseek" in model.lower():
            return await self._call_deepseek(model, system_msg, prompt)
        elif "groq" in model.lower() or "llama" in model.lower() or "qwen" in model.lower():
            return await self._call_groq(model, system_msg, prompt)
        elif "ollama" in model.lower() or "localhost" in model.lower():
            return await self._call_ollama(model, system_msg, prompt)
        elif "claude" in model.lower():
            return await self._call_anthropic(model, system_msg, prompt)
        else:
            return await self._call_openai(model, system_msg, prompt)

    async def _call_gemini(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "", "Missing GEMINI_API_KEY environment variable"

        clean_model = "gemma-4-26b-a4b-it" if model.lower() in ("gemini", "default", "gemini-2.0-flash") else model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        full_content = f"{system}\n\n{user_prompt}" if system else user_prompt
        payload = {
            "contents": [{"role": "user", "parts": [{"text": full_content}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return extract_diff_and_explanation(text)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            return "", f"Gemini API error: {exc}"

    async def _call_openai(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return "", "Missing OPENAI_API_KEY environment variable"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions", headers=headers, json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return extract_diff_and_explanation(text)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            return "", f"OpenAI API error: {exc}"

    async def _call_deepseek(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return "", "Missing DEEPSEEK_API_KEY environment variable"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    "https://api.deepseek.com/chat/completions", headers=headers, json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return extract_diff_and_explanation(text)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            return "", f"DeepSeek API error: {exc}"

    async def _call_groq(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return "", "Missing GROQ_API_KEY environment variable"

        clean_model = "qwen/qwen3.8-27b" if model.lower() in ("groq", "default", "llama-3.3-70b-versatile") else model
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": clean_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return extract_diff_and_explanation(text)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            return "", f"Groq API error: {exc}"

    async def _call_ollama(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        clean_model = model.replace("ollama/", "")
        payload = {
            "model": clean_model,
            "system": system,
            "prompt": user_prompt,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post("http://localhost:11434/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("response", "")
                return extract_diff_and_explanation(text)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            return "", f"Ollama API error: {exc}"

    async def _call_anthropic(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            # Automatic fallback to Gemini or OpenAI if Claude key not present
            fallback_model = get_recommended_model_for_persona(PersonaType.SURGICAL_MINIMALIST)
            if "gemini" in fallback_model or "gemma" in fallback_model:
                return await self._call_gemini(fallback_model, system, user_prompt)
            return await self._call_openai(fallback_model, system, user_prompt)

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages", headers=headers, json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["content"][0]["text"]
                return extract_diff_and_explanation(text)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            return "", f"Anthropic API error: {exc}"
