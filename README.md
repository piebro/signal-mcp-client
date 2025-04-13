# Signal MCP Client

An MCP client that uses signal for sending and receiving texts.


## Setup Signal Chat

These Instructions are for Linux. With some minor modification this should also work on a Mac or Windows.
I recommended to use an extra phone number for the bot, so you don't have to use your own.

1. Clone the repository: `git clone https://github.com/piebro/signal-mcp-client.git` 
2. Save your Anthropic API key (or use another LLM provider) in .env: `echo "ANTHROPIC_API_KEY='your-key'" > .env`
3. You will need a spare phone number that will be the phone number of your bot. Save that number in .env: `echo "SIGNAL_PHONE_NUMBER='+123456'" >> .env`
4. Rename `example.config.json` to `config.json` and add more mcp servers to it.
5. Install podman: `sudo apt install podman`
6. Start the [Signal CLI Rest Server](https://github.com/bbernhard/signal-cli-rest-api): `podman run -p 8080:8080 -e 'MODE=json-rpc' docker.io/bbernhard/signal-cli-rest-api:latest`
7. Scan the QR code here http://localhost:8080/v1/qrcodelink?device_name=signal-api for linking the bot to your signal account:
8. Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
9. Start the signal_chat: `uv run signal_mcp_client/main.py`


## Setup on a Raspberry Pi (Zero 2 W)

The Setup on a Raspberry Pi is basically the same as the instructions above.
I run the client on a Raspberry Pi Zero 2 W, but any Raspberry Pi should work.

Running the `signal-cli-rest-api` container on the Raspberry Pi might take a while (~15 minutes or more), but it should eventually start. Then use `ssh -L 8080:localhost:8080 user@pi.local` to create a tunnel to the Raspberry Pi and open the QR code in your browser.


## Adding MCP Server

Add the MCP server in the `config.json` file.

Here are some example servers I use:
- [watch-movie-mcp-server](https://github.com/piebro/watch-movie-mcp-server): Start a Movie using your bot (my Raspberry Pi is connected to a beamer)


## Using different LLM models

You can change the default LLM in settings.py and add more available models.
Then you can prompt the bot to use a different model.
For each model provider you will need to set the API key in .env.
Have a look at https://docs.litellm.ai/docs/providers for a list of supported models.

- Anthropic models: `ANTHROPIC_API_KEY`
- Mistral models: `MISTRAL_API_KEY`
- OpenAI models: `OPENAI_API_KEY`
- Gemini models: `GEMINI_API_KEY`

## Development

### Formatting and Linting

The code is formatted and linted with ruff:

```bash
uv run ruff format
uv run ruff check --fix
```