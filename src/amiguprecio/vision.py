"""Validación local y análisis visual acotado mediante Groq."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
VISION_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class ImageValidationError(ValueError):
    """El archivo aportado no cumple las reglas de seguridad visual."""


class VisionProviderError(RuntimeError):
    """Groq no produjo una observación visual utilizable."""


class VisualAnalysis(BaseModel):
    """Observaciones aparentes; nunca inferencias productivas o comerciales."""

    model_config = ConfigDict(extra="forbid")

    apparent_type: str = Field(min_length=1, max_length=160)
    predominant_colors: list[str] = Field(min_length=1, max_length=8)
    shape_and_details: list[str] = Field(min_length=1, max_length=12)
    comparison_features: list[str] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(min_length=1, max_length=12)
    model: str
    component: str = "Groq vision tool"


class VisionUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class VisionCallResult(BaseModel):
    analysis: VisualAnalysis
    http_status: int
    finish_reason: str | None = None
    usage: VisionUsage = Field(default_factory=VisionUsage)


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    sha256: str

    def as_data_url(self) -> str:
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.mime_type};base64,{encoded}"


def prepare_uploaded_image(data: bytes) -> PreparedImage:
    """Comprueba píxeles reales y recodifica sin EXIF ni otros metadatos."""

    if not data:
        raise ImageValidationError("La imagen está vacía")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError("La imagen supera el límite de 5 MB")
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            image_format = (source.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                raise ImageValidationError("Solo se admiten JPEG, PNG y WebP")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ImageValidationError("La imagen tiene demasiados píxeles")
            clean = ImageOps.exif_transpose(source)
            clean.load()
            if image_format == "JPEG":
                clean = clean.convert("RGB")
            elif clean.mode not in {"RGB", "RGBA"}:
                clean = clean.convert("RGBA" if "transparency" in source.info else "RGB")
            output = io.BytesIO()
            save_options: dict[str, Any] = {}
            if image_format == "JPEG":
                save_options = {"quality": 90, "optimize": True}
            elif image_format == "WEBP":
                save_options = {"quality": 90, "method": 4}
            clean.save(output, format=image_format, **save_options)
            cleaned_data = output.getvalue()
            width, height = clean.size
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageValidationError("El archivo no contiene una imagen válida") from exc
    if len(cleaned_data) > MAX_IMAGE_BYTES:
        raise ImageValidationError("La imagen recodificada supera el límite de 5 MB")
    return PreparedImage(
        data=cleaned_data,
        mime_type=ALLOWED_FORMATS[image_format],
        width=width,
        height=height,
        sha256=hashlib.sha256(cleaned_data).hexdigest(),
    )


def _safe_provider_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "respuesta no JSON"
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    error_type = error.get("type", "error del proveedor")
    return str(error_type)[:120]


def analyze_image_with_groq(
    image: PreparedImage,
    *,
    timeout_seconds: float = 60,
) -> VisionCallResult:
    """Envía los píxeles recodificados una sola vez al endpoint oficial de Groq."""

    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise VisionProviderError("Falta GROQ_API_KEY")
    configured_model = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    model = configured_model.removeprefix("groq/")
    prompt = (
        "Analiza solo lo que resulta visible en la fotografía del producto artesanal. "
        "Devuelve JSON con apparent_type, predominant_colors, shape_and_details, "
        "comparison_features y limitations. No infieras tamaño exacto, material exacto, "
        "horas, costes, calidad, seguridad, demanda ni ventas. Incluye esas incertidumbres "
        "en limitations, formuladas siempre como 'La fotografía no permite determinar...'; "
        "no afirmes que esos datos sean globalmente desconocidos. Usa arrays de cadenas "
        "breves y ningún texto fuera del JSON."
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image.as_data_url()},
                    },
                ],
            }
        ],
        "temperature": 0,
        "max_completion_tokens": 700,
        "reasoning_effort": "none",
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    try:
        response = httpx.post(
            VISION_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise VisionProviderError(f"Error de red de Groq: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise VisionProviderError(
            f"Groq devolvió HTTP {response.status_code}: {_safe_provider_message(response)}"
        )
    try:
        body = response.json()
        choice = body["choices"][0]
        content = choice["message"]["content"]
        parsed = json.loads(content)
        parsed["model"] = model
        analysis = VisualAnalysis.model_validate(parsed)
        usage = VisionUsage.model_validate(body.get("usage", {}))
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
        raise VisionProviderError("Groq devolvió una salida visual no válida") from exc
    return VisionCallResult(
        analysis=analysis,
        http_status=response.status_code,
        finish_reason=choice.get("finish_reason"),
        usage=usage,
    )
