"""
Chat model for the pipeline-analysis LLM helpers (LLM_activities_descriptor,
LLM_activities_used_columns, LLM_formatter).

Backend chosen by env var PROXAI_LLM_BACKEND:

  ollama  (default)  local, no rate limits.  OLLAMA_MODEL (default qwen2.5:7b),
                     OLLAMA_BASE_URL (default http://localhost:11434)
  groq               ChatGroq.  GROQ_MODEL (default openai/gpt-oss-120b),
                     uses the api_key passed in.

Default is Ollama because Groq's free tier (8000 tokens/min, 200000 tokens/day)
cannot sustain a multi-config stress-test sweep -- see stress_test/ISSUE.md.
"""

import os


def make_chat(api_key: str = None, temperature: float = 0, max_tokens: int = 4000):
    backend = os.getenv("PROXAI_LLM_BACKEND", "ollama").lower()

    if backend == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            temperature=temperature,
            groq_api_key=api_key,
            model_name=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            max_tokens=max_tokens,
        )

    from langchain_ollama import ChatOllama
    return ChatOllama(
        temperature=temperature,
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        num_predict=max_tokens,
    )
