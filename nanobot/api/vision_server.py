"""Vision service and minimal HTTP endpoint helpers."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider

_DATA_URI_RE = re.compile(r"^data:(?P<mime>[-\w.+/]+);base64,(?P<data>[A-Za-z0-9+/=]+)$")


@dataclass(slots=True)
class VisionAnalyzeResult:
    success: bool
    result: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "result": self.result, "error": self.error}


class VisionService:
    """VLM-backed image analysis helper."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        max_image_bytes: int = 2 * 1024 * 1024,
        default_prompt: str = "Describe the scene with key obstacles and safety hints.",
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_image_bytes = max(64 * 1024, max_image_bytes)
        self.default_prompt = default_prompt

    async def analyze_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = str(payload.get("question") or payload.get("prompt") or self.default_prompt)
        image = payload.get("image_base64") or payload.get("image_data_uri") or payload.get("image")
        mime = str(payload.get("mime") or "image/jpeg")
        return (await self.analyze(question=question, image=image, mime=mime)).to_dict()

    async def analyze(
        self,
        *,
        question: str,
        image: str | bytes | None,
        mime: str = "image/jpeg",
    ) -> VisionAnalyzeResult:
        if not image:
            return VisionAnalyzeResult(False, "", "missing image payload")

        try:
            b64_data, mime = self._normalize_image(image, mime=mime)
        except ValueError as e:
            return VisionAnalyzeResult(False, "", str(e))

        if len(base64.b64decode(b64_data)) > self.max_image_bytes:
            return VisionAnalyzeResult(False, "", "image exceeds configured size limit")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64_data}"}},
                ],
            }
        ]
        try:
            response = await self.provider.chat(
                messages=messages,
                model=self.model,
                temperature=0.1,
                max_tokens=1024,
            )
            content = (response.content or "").strip()
            if not content:
                return VisionAnalyzeResult(False, "", "empty model response")
            return VisionAnalyzeResult(True, content)
        except Exception as e:
            logger.warning(f"Vision analyze failed: {e}")
            return VisionAnalyzeResult(False, "", f"vision model call failed: {e}")

    @staticmethod
    def _normalize_image(image: str | bytes, *, mime: str) -> tuple[str, str]:
        if isinstance(image, bytes):
            return base64.b64encode(image).decode("ascii"), mime

        text = image.strip()
        match = _DATA_URI_RE.match(text)
        if match:
            return match.group("data"), match.group("mime")

        try:
            base64.b64decode(text, validate=True)
            return text, mime
        except Exception as e:
            raise ValueError(f"invalid image base64 payload: {e}") from e


def json_response(data: dict[str, Any]) -> bytes:
    """Serialize JSON response payload."""
    return json.dumps(data, ensure_ascii=False).encode("utf-8")

