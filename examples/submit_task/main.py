"""示例:提交一个 L4 任务(真发 A2A)

跑法:
    cd examples/submit_task && python3 main.py "What is the capital of France?"

期望:kernel 选 Whis,返 "Paris"
"""

import sys

import wau_sdk


def main() -> None:
    prompt = sys.argv[1] if len(sys.argv) > 1 else "What is the capital of France?"

    with wau_sdk.Client("http://localhost:18400") as c:
        resp = c.tasks.submit(wau_sdk.SubmitRequest(
            prompt=prompt,
            timeout_ms=30000,
        ))

    print(f"✅ 状态: {resp.status}")
    print(f"🤖 选中 agent: {resp.selected_agent} (score={resp.score:.2f})")
    print(f"📊 L3 决策: {resp.decision.decision_time_ms}ms | A2A 调用: {resp.a2a_call_ms}ms")
    print(f"💬 响应: {resp.response}")


if __name__ == "__main__":
    main()
