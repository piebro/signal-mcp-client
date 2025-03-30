import asyncio
import os
import sys
from contextlib import AsyncExitStack

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

import history
import mcp_client
from settings import initialize_settings_database

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Error: ANTHROPIC_API_KEY not found in environment variables.")
    sys.exit(1)


async def main():
    history.initialize_database()
    initialize_settings_database()

    session_id = "terminal"
    print(f"Session ID: {session_id}")
    history.clear_history(session_id)

    anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    async with AsyncExitStack() as exit_stack:
        mcp_config = mcp_client.load_mcp_config()
        tool_name_to_session, tools = await mcp_client.connect_to_servers(mcp_config, exit_stack)

        while True:
            try:
                user_input = input("You: ")
            except EOFError:
                print("\nExiting...")
                break

            if user_input.lower() in ["/quit", "/exit"]:
                print("Exiting...")
                break
            elif not user_input.strip():
                continue

            history.add_user_message(session_id, user_input)
            async for message in mcp_client.process_conversation_turn(
                anthropic_client, session_id, tools, tool_name_to_session
            ):
                print(message)

    print("\nCleanup complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
