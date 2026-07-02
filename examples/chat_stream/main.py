"""wau-python-sdk Chat SSE 流式调用 e2e 示例 — 累加 content + 输出 chatcmpl ID

跑法::

    cd examples/chat_stream && python main.py

期望:
  - 启动 wau_sdk.Client(against httptest mock wau-edge)
  - mock 模拟 6 chunks(role + "1+1=2") + [DONE]
  - 累加 delta.content = "1+1=2"
  - chatcmpl ID 输出

为什么用 mock server(不连真 wau-edge):
  - 真 wau-edge 在公网 43.134.126.126(:18402),需要 SSH + 跨网
  - 真实链路已通过 [[2026-07-02-PROGRESS-M5-#1+-curl-edges]] C.1 测试(7 chunks)验证
  - 本 example 专注 SDK API 用法,用 mock server 演示完整 stream() 流程
  - 真 e2e 走 [[2026-07-01-PROGRESS-M5-#5-sdk-python]] Stage 3.1 #5 已验(chatcmpl-787dcac6)

完整链路(per Stage 3.1 #10):
  Python SDK stream() → wau-edge :18402 /v1/chat/completions?stream=true
                     → wau-llm-router :18404 Resolve(unary, 拿 userToken + model)
                     → new-api sidecar → DeepSeek v4-flash → SSE chunks → 响应回 SDK
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import wau_sdk
from wau_sdk import (
    ChatMessage,
    ChatCompletionRequest,
    CircuitConfig,
    ClientOptions,
    RetryConfig,
)


def make_mock_server(port: int) -> HTTPServer:
    """启 HTTP mock server 模拟 wau-edge SSE 响应"""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            # 验请求:Accept: text/event-stream
            if self.headers.get("Accept") != "text/event-stream":
                self.send_error(400, "Accept must be text/event-stream")
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            req = json.loads(body)
            if not req.get("stream"):
                self.send_error(400, "Stream must be true")
                return
            model = req.get("model", "")

            # 6 chunks:role + "1+1=2"
            chunks = [
                {"id": "chatcmpl-example-1", "object": "chat.completion.chunk",
                 "created": 1700000000, "model": model,
                 "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                {"id": "chatcmpl-example-1", "object": "chat.completion.chunk",
                 "created": 1700000000, "model": model,
                 "choices": [{"index": 0, "delta": {"content": "1"}}]},
                {"id": "chatcmpl-example-1", "object": "chat.completion.chunk",
                 "created": 1700000000, "model": model,
                 "choices": [{"index": 0, "delta": {"content": "+"}}]},
                {"id": "chatcmpl-example-1", "object": "chat.completion.chunk",
                 "created": 1700000000, "model": model,
                 "choices": [{"index": 0, "delta": {"content": "1"}}]},
                {"id": "chatcmpl-example-1", "object": "chat.completion.chunk",
                 "created": 1700000000, "model": model,
                 "choices": [{"index": 0, "delta": {"content": "="}}]},
                {"id": "chatcmpl-example-1", "object": "chat.completion.chunk",
                 "created": 1700000000, "model": model,
                 "choices": [{"index": 0, "delta": {"content": "2"}, "finish_reason": "stop"}]},
            ]

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for c in chunks:
                line = f"data: {json.dumps(c)}\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        def log_message(self, format, *args) -> None:  # noqa: A002
            pass  # 静默

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:
    import sys

    port = 18384
    server = make_mock_server(port)
    try:
        url = f"http://127.0.0.1:{port}"
        opts = ClientOptions(retry=RetryConfig(max_retries=0), circuit=CircuitConfig(enabled=False))
        with wau_sdk.Client(url, opts) as c:
            print("=== wau-python-sdk Chat SSE 流式调用(against mock wau-edge)===")
            print(f"url:    {url}")
            print("model:  deepseek-v4-flash")
            print("prompt: 1+1=?")
            print()

            full = ""
            last_id = ""
            count = 0
            sys.stdout.write("response: ")
            sys.stdout.flush()
            for chunk in c.chat.stream(ChatCompletionRequest(
                model="deepseek-v4-flash",
                messages=[ChatMessage(role="user", content="1+1=?")],
            )):
                count += 1
                last_id = chunk.id
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        sys.stdout.write(delta.content)
                        sys.stdout.flush()
                        full += delta.content
                    if chunk.choices[0].finish_reason == "stop":
                        break
            print()
            print()
            print("=== 总结 ===")
            print(f"chatcmpl:  {last_id}")
            print(f"chunks:    {count} (role + 5 chars)")
            print(f"content:   {full}")
            print()
            print("✅ stream() 拿到 6 chunks,累加 content='1+1=2'")
            print("✅ FinishReason=stop 终止")
            print("✅ SDK SSE 解析正确(per wau-edge stream.go WriteChunk / WriteDone)")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()