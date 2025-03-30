import os
import json
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from litellm import completion

from settings import get_settings, update_settings, reset_settings, AVAILABLE_MODELS
import history

MAX_TOKENS = 2048

DEFAULT_TOOLS = [
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
                    }
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
]


def load_mcp_config():
    """Loads MCP server configuration from config.json"""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return json.load(f)
    print("WARN: config.json not found. No MCP servers will be configured.")
    return {"servers": []}


async def connect_to_servers(config, exit_stack: AsyncExitStack):
    """Connects to MCP servers defined in the config using a provided AsyncExitStack."""
    servers = config.get("servers", [])

    tools = [*DEFAULT_TOOLS]
    tool_name_to_session = {}

    print(f"Attempting to connect to {len(servers)} MCP server(s)...")
    for i, server_config in enumerate(servers):
        server_name = server_config.get("name", f"Server_{i + 1}")
        print(f"Connecting to MCP Server: {server_name} ({server_config.get('command', 'N/A')})")
        try:
            server_params = StdioServerParameters(
                command=server_config.get("command"), args=server_config.get("args", []), env=server_config.get("env")
            )

            stdio_transport = await exit_stack.enter_async_context(stdio_client(server_params))
            stdio, write = stdio_transport

            session = ClientSession(stdio, write)
            await exit_stack.enter_async_context(session)

            await session.initialize()
            print(f"[{server_name}] MCP Session Initialized.")

            response = await session.list_tools()
            print(f"[{server_name}] Found {len(response.tools)} tool(s).")

            for tool in response.tools:
                if tool.name in tool_name_to_session:
                    print(f"WARN: Duplicate tool name '{tool.name}' found. Overwriting previous entry.")
                tool_name_to_session[tool.name] = session
                tools.append({"name": tool.name, "description": tool.description, "input_schema": tool.inputSchema})
                print(f"  - Registered tool: {tool.name}")

        except Exception as e:
            print(f"ERROR: Failed to connect or initialize MCP server '{server_name}': {e}")

    print(f"Connected to MCP servers. Total tools available: {len(tools)}")
    return tool_name_to_session, tools


async def execute_tool_call(session_id, tool_name_to_session, tool_name, tool_arguments):
    """Executes a tool call using the appropriate MCP session."""
    if tool_name == "update_settings":
        print(f"update settings with: {tool_arguments}")
        update_settings(session_id, **tool_arguments)
        return "settings updated"
    elif tool_name == "get_settings":
        current_settings = get_settings(session_id)
        print(f"the current settings are: {current_settings}")
        return ", ".join([f"{key}: {value}" for key, value in current_settings.items()])
    elif tool_name == "reset_settings":
        print("reset settings to default")
        return reset_settings(session_id)
    elif tool_name == "reset_chat_history":
        history.clear_history(session_id)
        
        return "successfully deleted the chat history"


    session = tool_name_to_session.get(tool_name)
    if not session:
        return f"Error: Tool '{tool_name}' is not available."

    try:
        result = await session.call_tool(tool_name, tool_arguments)
        # Ensure result is a string or simple JSON string for history/Claude
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result)
    except Exception as e:
        return f"Error executing tool '{tool_name}': {e}"


async def process_conversation_turn(session_id, tools, tool_name_to_session, user_message=None, images_data_url=None):
    
    settings = get_settings(session_id)
    
    history.add_user_message(session_id, user_message, images_data_url)
    
    tool_used = False
    try:
        messages = history.get_history(session_id, limit=settings["llm_chat_message_context_limit"])
        if settings["system_prompt"] is not None and settings["system_prompt"].lower() != "none":
            messages = [{"role": "system", "content": settings["system_prompt"]}, *messages]

        response = completion(
            model=settings["model_name"],
            messages=messages,
            tools=tools,
            max_tokens=MAX_TOKENS,
        )

        for choice in response.choices:
            message = choice.message
            history.add_assistant_message(session_id, message.content, message.tool_calls)
            if message.content:
                # TODO: if message.tool_calls: maybe dont show the text? IDK
                yield {"text": message.content}
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_used = True

                    tool_id = tool_call.id
                    tool_name = tool_call.function.name
                    tool_arguments = json.loads(tool_call.function.arguments)
                    
                    args_str = ", ".join([f"{k}={v!r}" for k, v in tool_arguments.items()])
                    yield {"tool_use": f"{tool_name}({args_str})"}

                    tool_result_content = await execute_tool_call(session_id, tool_name_to_session, tool_name, tool_arguments)
                    print("tool_result_content: ", tool_result_content)
                    if tool_name == "reset_chat_history":
                        history.add_assistant_message(session_id, message.content, message.tool_calls)

                    history.add_tool_response(session_id, tool_id, tool_name, tool_result_content)
                    yield {"tool_result": f"{tool_result_content}"}

    except Exception as e:
        print(f"ERROR during Anthropic API call: {e}")
        return

    if tool_used:
        async for item in process_conversation_turn(session_id, tools, tool_name_to_session):
            yield item
