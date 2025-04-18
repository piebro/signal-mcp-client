import asyncio
import base64
import json
import logging
import os
import sys
import traceback
from contextlib import AsyncExitStack
from pathlib import Path

import mcp_client
import requests
import websockets
from dotenv import load_dotenv

load_dotenv()

WS_BASE_URL = "ws://localhost:8080"
HTTP_BASE_URL = "http://localhost:8080"
CLIENT_LOG_LEVEL = logging.DEBUG
SERVER_LOG_LEVEL = logging.DEBUG

log_format = "[%(levelname)s] [%(name)s] %(message)s"
formatter = logging.Formatter(log_format)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)

client_logger = logging.getLogger("signal_mcp_client")
client_logger.addHandler(handler)
client_logger.setLevel(CLIENT_LOG_LEVEL)

SIGNAL_PHONE_NUMBER = os.getenv("SIGNAL_PHONE_NUMBER")
if not SIGNAL_PHONE_NUMBER:
    client_logger.error("SIGNAL_PHONE_NUMBER not found in environment variables.")
    sys.exit(1)


def send_message(recipient, content):
    """Send a text message using the Signal API (Synchronous)"""
    if not content or not content.strip():
        client_logger.info(f"Skipping empty text message send to {recipient}")
        return
    url = f"{HTTP_BASE_URL}/v2/send"
    payload = {"number": SIGNAL_PHONE_NUMBER, "recipients": [recipient], "message": content}
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    client_logger.info(f"Successfully sent text message to {recipient}")


def send_attachment(session_id, recipient, content, filenames):
    url = f"{HTTP_BASE_URL}/v2/send"
    payload = {"number": SIGNAL_PHONE_NUMBER, "recipients": [recipient], "message": content}
    payload["base64_attachments"] = []
    for filename in filenames:
        suffix = filename.split(".")[-1]
        if suffix == "jpg" or suffix == "jpeg" or suffix == "png":
            content_type = f"image/{suffix}"
        else:
            raise ValueError(f"Unsupported file type: {filename}")
        file_path = Path(__file__).parent.parent / "sessions" / session_id / "images" / filename
        with open(file_path, "rb") as f:
            base64_data = base64.b64encode(f.read()).decode("utf-8")
        payload["base64_attachments"].append(f"data:{content_type};filename={filename};base64,{base64_data}")

    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    client_logger.info(f"Successfully sent message and attachments {filenames} to {recipient}")


def save_image_attachment(session_id, attachment_id):
    url = f"{HTTP_BASE_URL}/v1/attachments/{attachment_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    attachment_data = response.content

    image_dir = Path(__file__).parent.parent / "sessions" / session_id / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    file_count = len(list(image_dir.glob("*")))
    _, ext = os.path.splitext(attachment_id)
    image_path = image_dir / f"image_{file_count:05d}{ext}"

    with open(image_path, "wb") as f:
        f.write(attachment_data)
    client_logger.info(f"Successfully fetched and saved attachment ID: {attachment_id} to {image_path}")
    return image_path.name


def save_attachments(session_id, attachments):
    image_filenames = []
    for attachment in attachments:
        content_type = attachment.get("contentType", "").lower()
        attachment_id = attachment.get("id")
        if content_type.startswith("image/") and attachment_id:
            image_filenames.append(save_image_attachment(session_id, attachment_id))
        else:
            client_logger.info("Ignoring attachments other then images")
    return image_filenames


async def process_signal_message(websocket, tools, tool_name_to_session):
    client_logger.info("Waiting for Signal messages...")
    # if a new message is received, before the previous one is processed, the message is added to the queue
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
        client_logger.info(f"--- New message from {session_id} ---")

        image_filenames = save_attachments(session_id, attachments)

        if len(image_filenames) > 0:
            img_filenames_str = ", ".join(image_filenames)
            user_message = f"[{img_filenames_str}]\n{user_message}"
            await asyncio.to_thread(send_message, sender, img_filenames_str)

        if user_message:
            client_logger.info(f"Received (processed): {user_message}")

        async for response in mcp_client.process_conversation_turn(
            session_id, tools, tool_name_to_session, user_message
        ):
            if "images" in response:
                if "text" not in response:
                    response["text"] = ""
                await asyncio.to_thread(send_attachment, session_id, sender, response["text"], response["images"])
            elif "text" in response:
                await asyncio.to_thread(send_message, sender, response["text"])

        client_logger.info(f"--- Finished processing for {session_id} ---")


async def main():
    async with AsyncExitStack() as exit_stack:
        client_logger.info("Starting MCP servers")
        tool_name_to_session, tools = await mcp_client.start_servers(exit_stack, handler, SERVER_LOG_LEVEL)

        websocket_url = f"{WS_BASE_URL}/v1/receive/{SIGNAL_PHONE_NUMBER}"

        while True:
            try:
                client_logger.info(f"Attempting to connect to WebSocket: {websocket_url}")
                async with websockets.connect(websocket_url, ping_interval=30, ping_timeout=30) as websocket:
                    client_logger.info("WebSocket connection established.")
                    await process_signal_message(websocket, tools, tool_name_to_session)
                client_logger.info("WebSocket connection closed. Will attempt to reconnect...")
            except Exception as e:
                client_logger.error(f"An unexpected error occurred in the main connection loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        client_logger.info("\nInterrupted by user. Exiting.")
    finally:
        client_logger.info("\nCleanup complete.")
