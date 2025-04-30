import argparse
import json
import logging
import os
import traceback
from contextlib import AsyncExitStack

from litellm import AuthenticationError, completion
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from signal_mcp_client import history
from signal_mcp_client.build_in_tools import get_build_in_tools, get_settings, run_build_in_tools

logger = logging.getLogger("signal_mcp_client")


async def debug_log_handler(params: types.LoggingMessageNotificationParams, server_logger: logging.Logger):
    if params.level == "debug":
        server_logger.debug(params.data)
    elif params.level in ["info", "notice"]:
        server_logger.info(params.data)
    elif params.level in ["warning", "alert"]:
        server_logger.warning(params.data)
    elif params.level in ["error", "critical", "emergency"]:
        server_logger.error(params.data)


async def start_servers(
    exit_stack: AsyncExitStack, args: argparse.Namespace, handler: logging.Handler, server_log_level_int: int
):
    """Connects to MCP servers defined in the config using a provided AsyncExitStack."""

    if os.path.exists(args.config):
        with open(args.config) as f:
            servers = json.load(f)["servers"]
    else:
        raise Exception(f"Error: config.json file {args.config} not found.")

    tools = get_build_in_tools(args.available_models)
    tool_name_to_session = {}

    logger.info(f"Attempting to connect to {len(servers)} MCP server(s)...")
    for i, server_config in enumerate(servers):
        server_name = server_config.get("name", f"Server_{i + 1}")
        logger.info(f"Connecting to MCP Server: {server_name} ({server_config.get('command')})")
        try:
            server_params = StdioServerParameters(
                command=server_config.get("command"), args=server_config.get("args", []), env=server_config.get("env")
            )

            stdio_transport = await exit_stack.enter_async_context(stdio_client(server_params))
            stdio, write = stdio_transport

            server_logger = logging.getLogger(server_name)
            server_logger.setLevel(server_log_level_int)
            server_logger.addHandler(handler)

            session = ClientSession(
                stdio, write, logging_callback=lambda params: debug_log_handler(params, server_logger)
            )
            await exit_stack.enter_async_context(session)

            await session.initialize()
            logger.info(f"[{server_name}] MCP Session Initialized.")

            response = await session.list_tools()
            logger.info(f"[{server_name}] Found {len(response.tools)} tool(s).")

            for tool in response.tools:
                if tool.name in tool_name_to_session:
                    logger.warning(f"Duplicate tool name '{tool.name}' found. Overwriting previous entry.")
                tool_name_to_session[tool.name] = session
                tools.append({"name": tool.name, "description": tool.description, "input_schema": tool.inputSchema})
                logger.info(f"  - Registered tool: {tool.name}")

        except Exception as e:
            logger.error(f"Failed to connect or initialize MCP server '{server_name}': {e}")

    logger.info(f"Connected to MCP servers. Total tools available: {len(tools)}")
    return tool_name_to_session, tools


async def execute_tool_call(args, session_id, tool_name_to_session, tool_name, tool_arguments):
    """Executes a tool call using the appropriate MCP session."""

    success, result = run_build_in_tools(args, session_id, tool_name, tool_arguments)
    if success:
        return result

    session = tool_name_to_session.get(tool_name)
    if not session:
        return f"Error: Tool '{tool_name}' is not available."

    try:
        result = await session.call_tool(tool_name, tool_arguments)
        return result.content[0].text
    except Exception as e:
        return f"Error executing tool '{tool_name}': {e}"


async def process_conversation_turn(session_id, args, tools, tool_name_to_session, user_message=None):
    settings = get_settings(args, session_id)
    session_dir = args.session_save_dir
    
    if user_message:
        history.add_user_message(session_dir, session_id, user_message)

    tool_used = False
    try:
        messages = history.get_history(session_dir, session_id, limit=settings["llm_chat_message_context_limit"])

        system_prompt = settings["system_prompt"]
        if system_prompt and system_prompt.lower() != "none":
            messages.insert(0, {"role": "system", "content": system_prompt})

        response = completion(
            model=settings["model_name"],
            messages=messages,
            tools=tools,
            max_tokens=2000,
        )

        message = response.choices[0].message
        history.add_assistant_message(session_dir, session_id, message.content, message.tool_calls)

        if message.tool_calls:
            tool_used = True
            for tool_call in message.tool_calls:
                tool_id = tool_call.id
                tool_name = tool_call.function.name
                tool_arguments = json.loads(tool_call.function.arguments)

                tool_result = await execute_tool_call(
                    args, session_id, tool_name_to_session, tool_name, tool_arguments
                )

                history.add_tool_response(session_dir, session_id, tool_id, tool_name, tool_result)
                
                if tool_name == "reply_to_user":
                    yield {
                        "text": tool_arguments["reply_message"],
                        "media_file_paths": tool_arguments.get("media_file_paths", []),
                    }
                else:
                    yield {}  # send empty message to trigger typing indicator

    except AuthenticationError as e:
        error_message = (
            f"AuthenticationError: Please check your API key for the model: {settings['model_name']}, error: {e}"
        )
        history.add_assistant_message(session_dir, session_id, error_message)
        yield {"text": error_message}
        stack_trace = traceback.format_exc()
        logger.error(error_message)
        logger.error(stack_trace)
        return
    except Exception as e:
        error_message = f"ERROR during LLM API call: {e}"
        yield {"text": error_message}
        history.add_assistant_message(session_dir, session_id, error_message)
        stack_trace = traceback.format_exc()
        logger.error(error_message)
        logger.error(stack_trace)
        return

    if tool_used:
        async for item in process_conversation_turn(session_id, args, tools, tool_name_to_session):
            yield item