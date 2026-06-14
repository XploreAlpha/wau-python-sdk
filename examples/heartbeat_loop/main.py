"""示例:agent 端定时心跳上报

模拟一个 agent 进程:每 60s 调一次 Heartbeat + 偶尔上报 load

跑法:
    cd examples/heartbeat_loop && python3 main.py my-agent

期望:每 60s 打印一次心跳日志
"""

import signal
import sys
import time

import wau_sdk

_agent_name = "demo-agent"
_stop = False


def _signal_handler(signum: int, frame: object) -> None:
    global _stop
    print(f"\n[收到信号 {signum},正在退出...]")
    _stop = True


def do_heartbeat(c: wau_sdk.Client, agent_id: str) -> None:
    if err := c.agents.heartbeat(agent_id):
        print(f"[{_now()}] ❌ heartbeat: {err}")
        return
    if err := c.agents.report_load(agent_id, wau_sdk.AgentLoad(
        active_tasks=0, max_capacity=10, cpu_usage=0.1, memory_usage=0.2,
    )):
        print(f"[{_now()}] ⚠️  report load: {err}")
        return
    print(f"[{_now()}] 💓 heartbeat ok")


def _now() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def main() -> None:
    global _agent_name
    if len(sys.argv) > 1:
        _agent_name = sys.argv[1]

    # Ctrl+C 处理
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    with wau_sdk.Client("http://localhost:18400") as c:
        # 注册 agent
        if err := c.agents.register(wau_sdk.AgentRegisterRequest(
            name=_agent_name,
            url=f"http://{_agent_name}:18800",
            description="demo agent for heartbeat example",
            skills=["demo", "test"],
        )):
            print(f"❌ Register: {err}")
            return
        print(f"✅ Agent {_agent_name!r} 已注册")

        # 立即跑一次
        do_heartbeat(c, _agent_name)

        # 每 60s 跑一次
        while not _stop:
            time.sleep(60)
            if _stop:
                break
            do_heartbeat(c, _agent_name)


if __name__ == "__main__":
    main()
