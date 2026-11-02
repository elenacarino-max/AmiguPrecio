from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from amiguprecio.agents import VisionAnalysisTool
from amiguprecio.vision import (
    ImageValidationError,
    analyze_image_with_groq,
    prepare_uploaded_image,
)

FIXTURE = Path(__file__).parent / "fixtures" / "authorized-amigurumi.png"


def test_uploaded_image_is_validated_and_reencoded_without_metadata() -> None:
    source = io.BytesIO()
    Image.new("RGB", (32, 24), "coral").save(
        source, format="JPEG", exif=b"Exif\x00\x00private-location"
    )

    prepared = prepare_uploaded_image(source.getvalue())

    assert prepared.mime_type == "image/jpeg"
    assert (prepared.width, prepared.height) == (32, 24)
    with Image.open(io.BytesIO(prepared.data)) as cleaned:
        assert not cleaned.getexif()


def test_invalid_or_oversized_upload_is_rejected() -> None:
    with pytest.raises(ImageValidationError):
        prepare_uploaded_image(b"not-an-image")
    with pytest.raises(ImageValidationError, match="5 MB"):
        prepare_uploaded_image(b"x" * (5 * 1024 * 1024 + 1))


def test_groq_request_contains_actual_data_url_and_validates_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = prepare_uploaded_image(FIXTURE.read_bytes())
    captured: dict[str, object] = {}

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        captured.update(kwargs["json"])
        request = httpx.Request("POST", str(args[0]))
        body = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "apparent_type": "conejo de ganchillo",
                                "predominant_colors": ["crema", "coral", "verde"],
                                "shape_and_details": ["orejas largas", "bufanda"],
                                "comparison_features": ["figura animal", "detalles bordados"],
                                "limitations": ["no permite conocer el material exacto"],
                            }
                        )
                    },
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setenv("GROQ_API_KEY", "test-secret")
    monkeypatch.setattr("amiguprecio.vision.httpx.post", fake_post)

    result = analyze_image_with_groq(prepared)

    image_url = captured["messages"][0]["content"][1]["image_url"]["url"]
    prompt = captured["messages"][0]["content"][0]["text"]
    assert image_url.startswith("data:image/png;base64,")
    assert len(image_url) > len(prepared.data)
    assert "no afirmes que esos datos sean globalmente desconocidos" in prompt
    assert result.analysis.apparent_type == "conejo de ganchillo"
    assert result.finish_reason == "stop"
    assert result.usage.total_tokens == 180


def test_vision_tool_turns_provider_failure_into_controlled_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = prepare_uploaded_image(FIXTURE.read_bytes())

    def fail(*args: object, **kwargs: object) -> object:
        raise httpx.ConnectError("offline")

    monkeypatch.setenv("GROQ_API_KEY", "test-secret")
    monkeypatch.setattr("amiguprecio.vision.httpx.post", fail)
    tool = VisionAnalysisTool(prepared)

    result = tool._run(action="analyze")

    assert result["status"] == "failed"
    assert tool.last_result is None
    assert "test-secret" not in str(result)
