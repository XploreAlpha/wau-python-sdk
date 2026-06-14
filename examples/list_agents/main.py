"""示例:列出所有在线 agents

跑法:
    cd examples/list_agents && python3 main.py

期望:打印 3 个 agent(Whis/Jarvis/Benny)的 name / trust / status
"""

import wau_sdk


def main() -> None:
    with wau_sdk.Client("http://localhost:18400") as c:
        resp = c.agents.list(wau_sdk.PageOptions(page=1, pageSize=10))

    print(f"在线 agents ({len(resp.agents)}):")
    for a in resp.agents:
        print(f"  - {a.name}  trust={a.trust:.2f}  status={a.status}  skills={a.skills}")


if __name__ == "__main__":
    main()
