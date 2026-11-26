# BugArena Diagnostic & Repair Report
**Tournament ID**: `tourn_7c919910`  
**Repository**: `D:\MCP server`  

## Tournament Leaderboard
| Rank | Candidate ID | Persona | Repro Passed | Regressions | Churn (LOC) | Complexity Δ | Score | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `cand_bug010_surgical` | surgical_minimalist | PASS | 0 | 10 | 0 | **97.0** | `CHAMPION` |
| 2 | `cand_bug010_contract` | contract_enforcer | PASS | 0 | 10 | 0 | **97.0** | `EVALUATED` |
| 3 | `cand_bug010_defensive` | defensive_guardian | PASS | 0 | 14 | 0 | **95.8** | `EVALUATED` |
| 4 | `cand_bug010_architectural` | architectural_fixer | PASS | 0 | 19 | 0 | **94.3** | `EVALUATED` |

## Winning Champion Patch
- **Candidate ID**: `cand_bug010_surgical`
- **Agent Persona**: `surgical_minimalist`
- **Lines Added / Deleted**: +7 / -3
- **Explanation**: Route explicit ollama/localhost prefixes before model family substring matching and align _call_anthropic fallback routing.

### Unified Diff
```diff
--- a/src/bugarena/tournament/providers/dispatcher.py
+++ b/src/bugarena/tournament/providers/dispatcher.py
@@ -173,8 +173,8 @@
-        if "gemini" in model.lower() or "gemma" in model.lower():
+        if "ollama" in model.lower() or "localhost" in model.lower():
+            return await self._call_ollama(model, system_msg, prompt)
+        elif "gemini" in model.lower() or "gemma" in model.lower():
             return await self._call_gemini(model, system_msg, prompt)
         elif "deepseek" in model.lower():
             return await self._call_deepseek(model, system_msg, prompt)
         elif "groq" in model.lower() or "llama" in model.lower() or "qwen" in model.lower():
             return await self._call_groq(model, system_msg, prompt)
-        elif "ollama" in model.lower() or "localhost" in model.lower():
-            return await self._call_ollama(model, system_msg, prompt)
@@ -323,3 +323,7 @@
             if "gemini" in fallback_model or "gemma" in fallback_model:
                 return await self._call_gemini(fallback_model, system, user_prompt)
+            if "deepseek" in fallback_model:
+                return await self._call_deepseek(fallback_model, system, user_prompt)
+            if "groq" in fallback_model or "llama" in fallback_model or "qwen" in fallback_model:
+                return await self._call_groq(fallback_model, system, user_prompt)
             return await self._call_openai(fallback_model, system, user_prompt)
```

### How to Apply This Fix
To apply this patch to your repository, save the diff above to `fix.patch` and run:
```bash
git apply fix.patch
```