"""MCP tool name constants (wau-python-sdk v1.3.2, per D87.6).

10 tool name 常量对齐 kernel `internal/protocol/mcp/tools.go` ToolXxx + handler routeToProtocol。
W3 D87.1 实装 8 sync tool,2 SSE tool (stream_message + subscribe_to_task) deferred to W5+。
"""

# 8 sync tools(W3 实装,镜像 wau-go-sdk mcpclient/tools.go)
TOOL_HEALTH_CHECK = "health_check"
TOOL_PARSE_AGENT_CARD = "parse_agent_card"
TOOL_SEND_MESSAGE = "send_message"
TOOL_GET_TASK = "get_task"
TOOL_LIST_TASKS = "list_tasks"
TOOL_CANCEL_TASK = "cancel_task"
TOOL_CREATE_TASK_PUSH_NOTIFICATION_CONFIG = "create_task_push_notification_config"
TOOL_GET_EXTENDED_AGENT_CARD = "get_extended_agent_card"

# 2 SSE tools(W5+ deferred,本 SDK 暂不暴露 typed wrapper)
TOOL_STREAM_MESSAGE = "stream_message"
TOOL_SUBSCRIBE_TO_TASK = "subscribe_to_task"

ALL_TOOL_NAMES = (
    TOOL_HEALTH_CHECK,
    TOOL_PARSE_AGENT_CARD,
    TOOL_SEND_MESSAGE,
    TOOL_STREAM_MESSAGE,
    TOOL_GET_TASK,
    TOOL_LIST_TASKS,
    TOOL_CANCEL_TASK,
    TOOL_SUBSCRIBE_TO_TASK,
    TOOL_CREATE_TASK_PUSH_NOTIFICATION_CONFIG,
    TOOL_GET_EXTENDED_AGENT_CARD,
)


def is_streaming_tool(tool_name: str) -> bool:
    """判断 tool 是不是 SSE 流式 tool (W5+ streaming)。"""
    return tool_name in (TOOL_STREAM_MESSAGE, TOOL_SUBSCRIBE_TO_TASK)