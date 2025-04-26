import asyncio
import base64
import json
import logging
import os
import sys
import tempfile
import traceback
from contextlib import AsyncExitStack
from pathlib import Path

import fal_client
import requests
import websockets
from dotenv import load_dotenv

from signal_mcp_client import mcp_client

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


def send_attachment(session_id, recipient, content, file_paths):
    url = f"{HTTP_BASE_URL}/v2/send"
    payload = {"number": SIGNAL_PHONE_NUMBER, "recipients": [recipient], "message": content}
    payload["base64_attachments"] = []
    for file_path in file_paths:
        suffix = file_path.split(".")[-1]
        if suffix == "jpg" or suffix == "jpeg" or suffix == "png":
            content_type = f"image/{suffix}"
        elif suffix == "mp4":
            content_type = "video/mp4"
        else:
            raise ValueError(f"Unsupported file type: {file_path}")
        with open(file_path, "rb") as f:
            base64_data = base64.b64encode(f.read()).decode("utf-8")
        payload["base64_attachments"].append(
            f"data:{content_type};filename={Path(file_path).name};base64,{base64_data}"
        )

    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    client_logger.info(f"Successfully sent message and attachments {file_paths} to {recipient}")


def send_typing_indicator(recipient):
    """Sends the typing indicator to the recipient."""
    url = f"{HTTP_BASE_URL}/v1/typing-indicator/{SIGNAL_PHONE_NUMBER}"
    payload = {"recipient": recipient}
    try:
        response = requests.put(url, json=payload, timeout=5)
        response.raise_for_status()
        client_logger.debug(f"Sent typing indicator to {recipient}")
    except requests.exceptions.RequestException as e:
        client_logger.warning(f"Failed to send typing indicator to {recipient}: {e}")


def clear_typing_indicator(recipient):
    """Clears the typing indicator for the recipient."""
    url = f"{HTTP_BASE_URL}/v1/typing-indicator/{SIGNAL_PHONE_NUMBER}"
    payload = {"recipient": recipient}
    try:
        response = requests.delete(url, json=payload, timeout=5)
        response.raise_for_status()
        client_logger.debug(f"Cleared typing indicator for {recipient}")
    except requests.exceptions.RequestException as e:
        client_logger.warning(f"Failed to clear typing indicator for {recipient}: {e}")


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
    return image_path


def save_image_attachments(session_id, attachments):
    image_file_paths = []
    for attachment in attachments:
        content_type = attachment.get("contentType", "").lower()
        attachment_id = attachment.get("id")
        if content_type.startswith("image/") and attachment_id:
            image_file_paths.append(save_image_attachment(session_id, attachment_id))
        else:
            client_logger.info("Ignoring attachments other then images")
    return image_file_paths


def transcribe_voice_message(attachments):
    audio_data = None
    for attachment in attachments:
        content_type = attachment.get("contentType", "").lower()
        attachment_id = attachment.get("id")
        if content_type == "audio/aac" and attachment_id:
            try:
                client_logger.info(f"Fetching audio attachment ID: {attachment_id}")
                url = f"{HTTP_BASE_URL}/v1/attachments/{attachment_id}"
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                audio_data = response.content
                client_logger.info(
                    f"Successfully fetched audio attachment ID: {attachment_id} ({len(audio_data)} bytes)"
                )
                # Process only the first audio file found
                break
            except Exception as e:
                client_logger.error(f"Failed to fetch audio attachment {attachment_id}: {e}")
                return False, None

    if not audio_data:
        return False, None

    client_logger.info("Transcribing fetched audio data...")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".aac") as temp_audio_file:
            temp_audio_file.write(audio_data)
            temp_audio_path = temp_audio_file.name
        client_logger.info(f"Audio data saved to temporary file: {temp_audio_path}")

        audio_url = fal_client.upload_file(temp_audio_path)
        client_logger.info(f"Uploaded audio file, URL: {audio_url}")
        os.remove(temp_audio_path)
        client_logger.info(f"Temporary file deleted: {temp_audio_path}")

        result = fal_client.subscribe(
            "fal-ai/whisper",
            arguments={
                "audio_url": audio_url,
                "task": "transcribe",
            },
        )
        client_logger.info(result)

        transcribed_text = result.get("text", "") if result else ""
        client_logger.info(f"Transcription result: {transcribed_text}")
        return True, transcribed_text
    except Exception as e:
        client_logger.error(f"Error during audio transcription: {e}")
        traceback.print_exc()
        if "temp_audio_path" in locals() and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
            client_logger.info(f"Temporary file deleted after error: {temp_audio_path}")
        return False, "[Error during transcription]"


async def process_signal_message(websocket, tools, tool_name_to_session):
    client_logger.info("Waiting for Signal messages...")
    async for message in websocket:
        data = json.loads(message)
        envelope = data.get("envelope", {})
        session_id = envelope.get("source")
        data_message = envelope.get("dataMessage", {})
        user_message = data_message.get("message", "")
        attachments = data_message.get("attachments", [])
        quote = data_message.get("quote")

        image_file_paths = save_image_attachments(session_id, attachments)
        success, transcribed_text = await asyncio.to_thread(transcribe_voice_message, attachments)
        if success:
            user_message = transcribed_text

        if quote and quote.get("text"):
            quoted_text = quote.get("text")
            for attachment in quote.get("attachments", []):
                # Image uploaded by the user don't usually have a filename,
                # so it's not clear if the image can be quoted
                filename = attachment.get("filename")
                if filename:
                    quoted_text += f" [{filename}]"

            user_message = f"{user_message}\n<quote>{quoted_text}</quote>"

        if not user_message and len(image_file_paths) == 0:
            client_logger.info(f"[{session_id}] No text message, transcription, or images to process. Skipping.")
            continue
        client_logger.info(f"--- [{session_id}] New message received ---")

        if len(image_file_paths) > 0:
            img_file_paths_str = ", ".join(str(image_file_path) for image_file_path in image_file_paths)
            user_message = f"[{img_file_paths_str}]\n{user_message}"
            await asyncio.to_thread(send_message, session_id, f"Received images: {img_file_paths_str}")

        client_logger.info(
            f"[{session_id}] Processing message for MCP: {user_message[:100]}{'...' if len(user_message) > 100 else ''}"
        )

        await asyncio.to_thread(send_typing_indicator, session_id)
        try:
            async for response in mcp_client.process_conversation_turn(
                session_id, tools, tool_name_to_session, user_message
            ):
                if "media_file_paths" in response:
                    if "text" not in response:
                        response["text"] = ""
                    client_logger.info(
                        f"[{session_id}] Sending attachment: {len(response['media_file_paths'])} media files"
                    )
                    await asyncio.to_thread(
                        send_attachment, session_id, session_id, response["text"], response["media_file_paths"]
                    )
                elif "text" in response:
                    client_logger.info(
                        f"[{session_id}] Sending text response: {response['text'][:100]}{'...' if len(response['text']) > 100 else ''}"
                    )
                    await asyncio.to_thread(send_message, session_id, response["text"])

                client_logger.info(f"[{session_id}] Is last message: {response.get('is_last_message', False)}")
                if not response.get("is_last_message", False):
                    await asyncio.to_thread(send_typing_indicator, session_id)

        except Exception as e:
            await asyncio.to_thread(clear_typing_indicator, session_id)
            client_logger.error(f"[{session_id}] Error during MCP processing: {e}")
            traceback.print_exc()

        client_logger.info(f"--- [{session_id}] Finished processing ---")


async def main_loop():
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


def main():
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        client_logger.info("\nInterrupted by user. Exiting.")
    finally:
        client_logger.info("\nCleanup complete.")


if __name__ == "__main__":
    main()
