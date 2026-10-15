import os
import httpx
import logging

logger = logging.getLogger("ws_llm_engine")

class RealTimeLLMRouter:
    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")

    async def generate_response(self, user_prompt: str) -> str:
        if not self.api_key or self.api_key == "your_llm_api_key_here":
            return f"[Local Engine Router]: Received prompt '{user_prompt}'. No LLM_API_KEY configured."

        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are Systems Builder, an elite software engineering architect producing production-grade code."},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                logger.error(f"Upstream LLM generation failed: {str(e)}")
                return "[Fallback Local Router]: Upstream LLM request failed. Try again."
