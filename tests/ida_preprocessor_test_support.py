from __future__ import annotations

import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path


class FakeStreamableHttpClient:
    async def __aenter__(self):
        return ("read-stream", "write-stream", None)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeClientSession:
    def __init__(self, read_stream, write_stream):
        self.read_stream = read_stream
        self.write_stream = write_stream

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def initialize(self):
        return None

    async def call_tool(self, name, arguments):
        return {"name": name, "arguments": arguments}


@asynccontextmanager
async def async_context(value):
    yield value


def load_module(script_path: str | Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(script_path))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeTextContent:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeCallToolResult:
    def __init__(self, payload: dict[str, object]) -> None:
        self.content = [FakeTextContent(json.dumps(payload))]


def py_eval_payload(payload: object) -> FakeCallToolResult:
    return FakeCallToolResult(
        {
            "result": json.dumps(payload),
            "stdout": "",
            "stderr": "",
        }
    )
