"""示例:跑 5 场景契约(模拟 wau-intent/e2e_test/test_submit_l4.py)

跑法:
    cd examples/five_scenarios && python3 main.py

期望:5/5 通过,跟真 kernel e2e 行为一致
"""

import wau_sdk

SCENARIOS = [
    ("clinical", "I need clinical decision support for a patient", "Jarvis",
     ["临床", "决策", "支持", "患者"]),
    ("france", "What is the capital of France?", "Whis", ["paris"]),
    ("pain", "Recommend an over-the-counter pain reliever", "Benny",
     ["ibuprofen", "acetaminophen"]),
    ("sales", "Show me this quarter's sales analytics", "Whis",
     ["sales", "analytics", "quarter"]),
    ("rare_disease", "Help me diagnose a rare disease", "Jarvis",
     ["罕见病", "鉴别", "诊断"]),
]


def main() -> None:
    with wau_sdk.Client("http://localhost:18400") as c:
        pass_, fail_ = 0, 0
        for scene, prompt, expected_agent, expected_tokens in SCENARIOS:
            print(f"\n=== {scene} ===")
            print(f"Prompt: {prompt}")

            try:
                resp = c.tasks.submit(wau_sdk.SubmitRequest(
                    prompt=prompt, timeout_ms=60000,
                ))
            except wau_sdk.APIError as e:
                print(f"   ❌ HTTP error: {e}")
                fail_ += 1
                continue

            if resp.status != "completed":
                print(f"   ❌ status={resp.status} err={resp.error}")
                fail_ += 1
                continue

            if resp.selected_agent != expected_agent:
                print(f"   ❌ 选了 {resp.selected_agent} (期望 {expected_agent})")
                fail_ += 1
                continue

            text = str(resp.response).lower()
            if not any(tok.lower() in text for tok in expected_tokens):
                print(f"   ❌ 响应里没找到期望 token")
                fail_ += 1
                continue

            print(f"   ✅ → {resp.selected_agent}  L3={resp.decision.decision_time_ms}ms "
                  f"A2A={resp.a2a_call_ms}ms")
            pass_ += 1

        print(f"\n=== 汇总: {pass_}/{len(SCENARIOS)} 通过 ===")


if __name__ == "__main__":
    main()
