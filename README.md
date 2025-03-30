# Signal MCP Client

An MCP client that uses signal for sending and receiving texts.

## Setup Signal Chat

These Instructions are for Linux. With some minor modification this should also work on a Mac or Windows.

1. Install [uv](https://docs.astral.sh/uv/).
2. Save your Anthropic API key in .env: `echo "ANTHROPIC_API_KEY='your-key'" > .env`
3. You will need a spare phone number that will be the phone number of your bot. Save that number in .env: `echo "SIGNAL_PHONE_NUMBER='+123456'" >> .env`
4. Install podman: `sudo apt install podman`
5. Start the Signal cli rest server: `podman run -p 8080:8080 -e 'MODE=json-rpc' docker.io/bbernhard/signal-cli-rest-api:latest`
6. Scan the QR code here http://localhost:8080/v1/qrcodelink?device_name=signal-api for linking the bot to your signal account: 
7. Start the signal_chat: `uv run signal_chat.py`
8. You should be now ready to go. Add some cool tools to config.json to take advantage of MCP.


## Setup Terminal Chat

1. Install [uv](https://docs.astral.sh/uv/).
2. Save your Anthropic API key in .env: `echo "ANTHROPIC_API_KEY='your-key'" > .env`
3. Start the terminal mcp client: `uv run terminal_chat.py`
4. You Should be ready to go.

## Adding MCP Server

Add the MCP server in the `config.json` file.

Here are some example servers I use:
- [watch-movie-mcp-server](https://github.com/piebro/watch-movie-mcp-server): Start a Movie using your bot.

## Development

Run these commands for formatting and linting

```bash
uvx ruff format --line-length=120
uvx ruff check --fix
```