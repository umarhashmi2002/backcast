"""Unit tests for the Lambda HTTP helpers (no AWS/DB)."""

from __future__ import annotations

import base64
import json

from backcast.api.http import json_response, parse_body


def test_parse_body_json_string() -> None:
    assert parse_body({"body": json.dumps({"a": 1})}) == {"a": 1}


def test_parse_body_direct_invoke() -> None:
    assert parse_body({"org_id": "x"}) == {"org_id": "x"}


def test_parse_body_dict_body() -> None:
    assert parse_body({"body": {"a": 1}}) == {"a": 1}


def test_parse_body_base64() -> None:
    encoded = base64.b64encode(b'{"a": 2}').decode("utf-8")
    assert parse_body({"body": encoded, "isBase64Encoded": True}) == {"a": 2}


def test_parse_body_empty() -> None:
    assert parse_body({"body": None}) == {}


def test_json_response_shape() -> None:
    response = json_response(201, {"ok": True})
    assert response["statusCode"] == 201
    assert response["headers"]["content-type"] == "application/json"
    assert json.loads(response["body"]) == {"ok": True}
