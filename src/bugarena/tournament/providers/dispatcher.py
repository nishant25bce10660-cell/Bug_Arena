"""Multi-model API dispatcher connecting competing personas to Anthropic, OpenAI, Gemini, and DeepSeek."""

import os
import re

import httpx

from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.personas.base import get_persona_prompt

# Recommended models mapped to persona strengths
PERSONA_MODEL_MAP = {
    PersonaType.SURGICAL_MINIMALIST: "claude-3-5-sonnet-20241022",
    PersonaType.DEFENSIVE_GUARDIAN: "gemini-2.0-flash",
    PersonaType.ARCHITECTURAL_FIXER: "o3-mini",
    PersonaType.CONTRACT_ENFORCER: "deepseek-reasoner",
}

DIFF_BLOCK_REGEX = re.compile(
    r"```(?:diff)?\n(--- (?:a/)?\S+\n\+\+\+ (?:b/)?\S+\n[\s\S]+?)```", re.MULTILINE
)
RAW_DIFF_REGEX = re.compile(r"(--- (?:a/)?\S+\n\+\+\+ (?:b/)?\S+\n@@[\s\S]+)", re.MULTILINE)


def get_recommended_model_for_persona(persona: PersonaType) -> str:
    """Return the optimal industry model for a specific repair persona."""
    return PERSONA_MODEL_MAP.get(persona, "claude-3-5-sonnet-20241022")


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
    """Dispatches repair prompts across Anthropic, OpenAI, Gemini, DeepSeek, or Ollama."""

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
        """
        model = model_override or get_recommended_model_for_persona(persona)
        prompt = build_repair_prompt(persona, bug_spec, repro_spec)
        system_msg = get_persona_prompt(persona)

        # Route by model identifier
        if "claude" in model.lower():
            return await self._call_anthropic(model, system_msg, prompt)
        elif "gemini" in model.lower():
            return await self._call_gemini(model, system_msg, prompt)
        elif "deepseek" in model.lower():
            return await self._call_deepseek(model, system_msg, prompt)
        elif "ollama" in model.lower() or "localhost" in model.lower():
            return await self._call_ollama(model, system_msg, prompt)
        else:
            return await self._call_openai(model, system_msg, prompt)

    async def _call_anthropic(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "", "Missing ANTHROPIC_API_KEY environment variable"

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
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"]
            return extract_diff_and_explanation(text)

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
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return extract_diff_and_explanation(text)

    async def _call_gemini(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "", "Missing GEMINI_API_KEY environment variable"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return extract_diff_and_explanation(text)

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
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                "https://api.deepseek.com/chat/completions", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return extract_diff_and_explanation(text)

    async def _call_ollama(self, model: str, system: str, user_prompt: str) -> tuple[str, str]:
        clean_model = model.replace("ollama/", "")
        payload = {
            "model": clean_model,
            "system": system,
            "prompt": user_prompt,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post("http://localhost:11434/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "")
            return extract_diff_and_explanation(text)
