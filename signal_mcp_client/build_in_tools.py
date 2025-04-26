import base64
import json
import logging
from pathlib import Path

from litellm import completion

from signal_mcp_client import history

logger = logging.getLogger("signal_mcp_client")

AVAILABLE_MODELS = json.load(open(Path(__file__).parent.parent / "available_model.json"))

BUILT_IN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_settings",
            "description": "Update the settings of the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "system_prompt": {
                        "type": "string",
                        "description": "The new system prompt for the current chat bot. If 'None', it defaults to no custom system prompt.",
                    },
                    "model_name": {
                        "type": "string",
                        "enum": AVAILABLE_MODELS,
                        "description": "The LLM model used for the conversation.",
                    },
                    "llm_chat_message_context_limit": {
                        "type": "integer",
                        "description": "The number of chat messages included into the context of the LLM.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_settings",
            "description": "Get the settings of the user.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reset_settings",
            "description": "Reset the user settings to the default settings.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reset_chat_history",
            "description": "Reset the chat history of ther user.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_images",
            "description": "Describe images and return a description of the images.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_filenames": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                        "description": "The filenames of the images to describe.",
                    },
                },
                "required": ["image_filenames"],
            },
        },
    },
]


def get_default_settings():
    return json.load(open(Path(__file__).parent.parent / "default_settings.json"))


def get_session_settings(session_id):
    session_settings_path = Path(__file__).parent.parent / "sessions" / session_id / "settings.json"
    if session_settings_path.exists():
        session_settings = json.load(open(session_settings_path))
    else:
        session_settings = {}
    return session_settings


def update_settings(session_id, **tool_arguments):
    logger.info(f"update settings with: {tool_arguments}")
    session_settings = get_session_settings(session_id)
    session_settings.update(tool_arguments)

    session_settings_path = Path(__file__).parent.parent / "sessions" / session_id / "settings.json"
    session_settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(session_settings_path, "w") as f:
        json.dump(session_settings, f)
    return True, "settings updated"


def get_settings(session_id):
    logger.info(f"get settings for session: {session_id}")
    settings = get_default_settings()
    session_settings = get_session_settings(session_id)
    settings.update(session_settings)
    return settings


def reset_settings(session_id):
    logger.info(f"reset settings for session: {session_id}")
    session_settings_path = Path(__file__).parent.parent / "sessions" / session_id / "settings.json"
    if session_settings_path.exists():
        session_settings_path.unlink()

    return True, "settings reset to default"


def reset_chat_history(session_id):
    logger.info(f"reset chat history for session: {session_id}")
    history.clear_history(session_id)
    return True, "chat history reset"


def describe_images(session_id, image_filenames):
    image_contents = []
    for image_filename in image_filenames:
        image_path = Path(__file__).parent.parent / "sessions" / session_id / "images" / image_filename
        if not image_path.exists():
            return True, f"Error: Image file '{image_filename}' not found."

        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            suffix = image_path.suffix.lstrip(".")
            if suffix == "jpg":
                suffix = "jpeg"
            image_contents.append(
                {"type": "image_url", "image_url": {"url": f"data:image/{suffix};base64,{base64_image}"}}
            )

    messages = [
        {"role": "system", "content": "You are a helpful assistant that can create a short description of the images."},
        {"role": "user", "content": image_contents},
    ]
    current_settings = get_settings(session_id)
    response = completion(
        model=current_settings["model_name"],
        messages=messages,
        max_tokens=500,
    )
    return True, response.choices[0].message.content


def run_build_in_tools(session_id, tool_name, tool_arguments):
    if tool_name == "update_settings":
        return update_settings(session_id, **tool_arguments)
    elif tool_name == "get_settings":
        current_settings = get_settings(session_id)
        return True, ", ".join([f"{key}: {value}" for key, value in current_settings.items()])
    elif tool_name == "reset_settings":
        return reset_settings(session_id)
    elif tool_name == "reset_chat_history":
        return reset_chat_history(session_id)
    elif tool_name == "describe_images":
        return describe_images(session_id, tool_arguments.get("image_filenames"))
    else:
        return False, None
