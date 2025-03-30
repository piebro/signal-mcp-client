import asyncio
import base64
import json
import os
import sys
import requests
from contextlib import AsyncExitStack

from dotenv import load_dotenv
import websockets

import history
import mcp_client
from settings import initialize_settings_database

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Error: ANTHROPIC_API_KEY not found in environment variables.")
    sys.exit(1)

SIGNAL_PHONE_NUMBER = os.getenv("SIGNAL_PHONE_NUMBER")
if not SIGNAL_PHONE_NUMBER:
    print("Error: SIGNAL_PHONE_NUMBER not found in environment variables.")
    sys.exit(1)

WS_BASE_URL = "ws://localhost:8080"
HTTP_BASE_URL = "http://localhost:8080"

def send_message(recipient, content):
    """Send a text message using the Signal API (Synchronous)"""
    if not content or not content.strip():
        print(f"Skipping empty text message send to {recipient}")
        return

    print(f"Sending text to {recipient}: {content[:50]}...") # Log truncated message
    url = f"{HTTP_BASE_URL}/v2/send"
    payload = {"number": SIGNAL_PHONE_NUMBER, "recipients": [recipient], "message": content}

    try:
        response = requests.post(url, json=payload, timeout=20) # Increased timeout slightly
        response.raise_for_status()
        print(f"Successfully sent text message to {recipient}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending Signal text message to {recipient}: {e}")
    except Exception as e:
         print(f"An unexpected error occurred in send_message: {e}")


def send_attachment(recipient, content_type, filename, base64_data):
    print(f"Sending attachment to {recipient}: {filename}")
    url = f"{HTTP_BASE_URL}/v2/send"
    payload = {
        "number": SIGNAL_PHONE_NUMBER,
        "recipients": [recipient],
        "message": "",
    }
    formatted_attachment = f"data:{content_type};filename={filename};base64,{base64_data}"
    payload["base64_attachments"] = [formatted_attachment]

    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    print(f"Successfully sent attachment {filename} to {recipient}")


def get_attachment_base64(attachment_id):
    print(f"Attempting to fetch attachment data for ID: {attachment_id}")
    url = f"{HTTP_BASE_URL}/v1/attachments/{attachment_id}"

    try:
        response = requests.get(url, timeout=30) # Timeout for download
        response.raise_for_status()
        attachment_data = response.content

        if attachment_data:
            base64_encoded_data = base64.b64encode(attachment_data).decode('utf-8')
            print(f"Successfully fetched and base64 encoded attachment ID: {attachment_id}")
            return base64_encoded_data
        else:
            print(f"Warning: Received empty data for attachment ID: {attachment_id}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching Signal attachment {attachment_id}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred in get_attachment_base64: {e}")
        return None


async def handle_websocket_message(websocket, tools, tool_name_to_session):
    """Handles incoming WebSocket messages from Signal, including images."""
    print("Waiting for Signal messages...")

    try:
        async for message in websocket:

            data = json.loads(message)
            envelope = data.get("envelope", {})
            sender = envelope.get("source")
            data_message = envelope.get("dataMessage", {})
            user_message = data_message.get("message", "")
            attachments = data_message.get("attachments", [])

            if not user_message and len(attachments) == 0:
                continue

            session_id = sender
            print(f"\n--- New message from {session_id} ---")

            images_data_url = []
            for attachment in attachments:
                content_type = attachment.get("contentType", "").lower()
                attachment_id = attachment.get("id")
                filename = attachment.get("filename", "attachment.bin")

                if content_type.startswith("image/") and attachment_id:
                    print(f"Attachment is an image ({content_type}), ID: {attachment_id}. Fetching base64 data...")
                    base64_data = await asyncio.to_thread(get_attachment_base64, attachment_id)
                    if base64_data:
                        images_data_url.append(f"data:{content_type};base64,{base64_data}")
                else:
                    print("Ignoring attachments other then images")

            if user_message:
                print(f"Received (processed): {user_message}")

            async for response in mcp_client.process_conversation_turn(session_id, tools, tool_name_to_session, user_message, images_data_url):
                if "text" in response:
                    await asyncio.to_thread(send_message, sender, response["text"])
                if "image" in response:
                    # TODO: make this correct here
                    content_type = "image/jpeg"
                    filename = "ok.jpg"
                    await asyncio.to_thread(send_attachment, sender, content_type, filename, response["text"])

            print(f"--- Finished processing for {session_id} ---")

    except websockets.exceptions.ConnectionClosedOK:
        print("WebSocket connection closed normally.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"WebSocket connection closed with error: {e}")
    except Exception as e:
        print(f"WebSocket connection error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("Initializing databases...")
    history.initialize_database()
    initialize_settings_database()
    print("Databases initialized.")

    async with AsyncExitStack() as exit_stack:
        print("Loading MCP configuration...")
        mcp_config = mcp_client.load_mcp_config()
        print("Connecting to MCP servers...")

        tool_name_to_session, tools = await mcp_client.connect_to_servers(mcp_config, exit_stack)

        websocket_url = f"{WS_BASE_URL}/v1/receive/{SIGNAL_PHONE_NUMBER}"

        # Main loop to handle WebSocket connection and reconnection
        while True:
            try:
                print(f"Attempting to connect to WebSocket: {websocket_url}")
                async with websockets.connect(websocket_url, ping_interval=30, ping_timeout=30) as websocket:
                    print("WebSocket connection established.")
                    await handle_websocket_message(websocket, tools, tool_name_to_session)
                print("WebSocket connection closed. Will attempt to reconnect...")

            except websockets.exceptions.InvalidURI:
                 print(f"Invalid WebSocket URI: {websocket_url}")
                 await asyncio.sleep(10) # Wait before retrying
            except websockets.exceptions.WebSocketException as e:
                 print(f"WebSocket connection failed: {e}")
                 await asyncio.sleep(5)  # Wait before reconnecting
            except ConnectionRefusedError:
                print("Connection refused. Is the signal-cli-rest-api running?")
                await asyncio.sleep(10) # Wait longer if connection is refused
            except Exception as e:
                print(f"An unexpected error occurred in the main connection loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(5) # Wait before retrying


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
    finally:
        print("\nCleanup complete.")