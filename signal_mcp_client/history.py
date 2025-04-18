import json
import os
import time
from datetime import datetime
from pathlib import Path


def get_history(session_id, limit):
    messages_dir = Path(__file__).parent.parent / "sessions" / session_id / "messages"
    if not messages_dir.exists():
        return []
    message_files = sorted(messages_dir.glob("*.json"))
    messages = [json.load(open(file_path)) for file_path in message_files[-limit:]]
    if messages[0]["role"] == "tool":
        messages = messages[1:]
    return messages


def add_message(session_id, message):
    messages_dir = Path(__file__).parent.parent / "sessions" / session_id / "messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    file_path = messages_dir / f"{int(time.time() * 1000)}.json"
    with open(file_path, "w") as f:
        json.dump(message, f, indent=2)


def clear_history(session_id):
    messages_dir = Path(__file__).parent.parent / "sessions" / session_id / "messages"
    if messages_dir.exists():
        for file_path in messages_dir.glob("*.json"):
            os.remove(file_path)


def add_user_message(session_id, content, images_data_url=None):
    content_for_message = []
    if content:
        now = datetime.now()
        timestamp_str = now.strftime("[%Y.%m.%d %H:%M]")
        content_for_message.append({"type": "text", "text": f"{timestamp_str} {content}"})
    if images_data_url:
        for image_data_url in images_data_url:
            content_for_message.append({"type": "image_url", "image_url": {"url": image_data_url}})

    if len(content_for_message) > 0:
        message = {"role": "user", "content": content_for_message}
        add_message(session_id, message)


def add_assistant_message(session_id, content, tool_calls=None):
    """Add a simple assistant text message."""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        temp_tool_calls = []
        for tool_call in tool_calls:
            temp_tool_calls.append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments},
                }
            )
        message["tool_calls"] = temp_tool_calls
    add_message(session_id, message)


def add_tool_response(session_id, tool_call_id, name, tool_result_text):
    """Add a tool response message."""
    message = {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": [{"type": "text", "text": tool_result_text}]}
    add_message(session_id, message)
