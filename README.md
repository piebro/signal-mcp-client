# Signal MCP Client

An MCP (Model Context Protocol) client that uses Signal for sending and receiving texts.

## Setup The Signal Chat Bot

These Instructions are for Linux. With some minor modification this should also work on a Mac or Windows.
I recommend to use an extra phone number for the bot, so you don't have to use your own.

1.  Clone the repository and navigate into the directory: 
    ```bash
    git clone https://github.com/piebro/signal-mcp-client.git
    cd signal-mcp-client
    ```
2.  Save your Anthropic API key (or use another LLM provider) and the bot's phone number in `.env`:
    ```bash
    cat << EOF > .env
    ANTHROPIC_API_KEY='your-key'
    SIGNAL_PHONE_NUMBER='+1234567890'
    EOF
    ```
3.  Rename `example.config.json` to `config.json`. You can add more MCP servers to it later.
    ```bash
    mv example.config.json config.json
    ```
4.  Install [uv](https://docs.astral.sh/uv/) and [podman](https://podman.io/):
    ```bash
    sudo apt install podman
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
5.  Replace `/home/USER_NAME` with your actual username and start the [Signal CLI Rest Server](https://github.com/bbernhard/signal-cli-rest-api) container:
    ```bash
    podman run \
        --name signal-cli-api-temp \
        -p 8080:8080 \
        -v /home/USER_NAME/.local/share/signal-api:/home/.local/share/signal-cli \
        -e 'MODE=json-rpc' \
        docker.io/bbernhard/signal-cli-rest-api:latest
    ```
6.  Connect the signal-cli-rest-api container to your signal account by opening this link and scanning the QR code: 
    ```
    http://localhost:8080/v1/qrcodelink?device_name=signal-api
    ```
7.  Start the MCP client: 
    ```bash
    uv run signal_mcp_client/main.py
    ```

## Adding MCP Server

Add the MCP server in the `config.json` file.

Here are some example servers I use:
- [watch-movie-mcp-server](https://github.com/piebro/watch-movie-mcp-server): Start a Movie using your bot (my Raspberry Pi is connected to a beamer)

## Using different LLM models

You can change the default LLM in `settings.py` and add more available models.
For each model provider you want to use, you will need to set the corresponding API key in your `.env` file.

Have a look at [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for a list of supported models.

Common environment variables for API keys in `.env`:
- Anthropic models: `ANTHROPIC_API_KEY`
- Mistral models: `MISTRAL_API_KEY`
- OpenAI models: `OPENAI_API_KEY`
- Gemini models: `GEMINI_API_KEY`
- Groq models: `GROQ_API_KEY`

## Development

### Formatting and Linting

The code is formatted and linted with ruff:

```bash
uv run ruff format
uv run ruff check --fix
```

## Running as a Systemd Service

To ensure the Signal REST API and the MCP Client run automatically on boot and restart if they fail, you can set them up as systemd user services.
User services run under your specific user account.

This setup assumes that you have completed the setup steps and your project is located at `/home/$USER/signal-mcp-client`.

1. Enable User Lingering to keep your user session active after logging out.
    ```bash
    sudo loginctl enable-linger $USER
    ```

2. Create Systemd Service Directory
    ```bash
    mkdir -p /home/$USER/.config/systemd/user/
    ```

3. Create Service File for Signal REST API 
    ```bash
    cat << EOF > "/home/$USER/.config/systemd/user/signal-cli-rest-api.service"
    [Unit]
    Description=Signal CLI REST API Container
    After=network.target
    Wants=network-online.target

    [Service]
    Environment="XDG_RUNTIME_DIR=/run/user/%U"
    Environment="DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus"
    SyslogIdentifier=signal-cli-rest-api
    Restart=on-failure
    RestartSec=30

    ExecStartPre=-/usr/bin/podman stop signal-cli-api
    ExecStartPre=-/usr/bin/podman rm signal-cli-api

    ExecStart=/usr/bin/podman run --name signal-cli-api \\
        -p 127.0.0.1:8080:8080 \\
        -v /home/$USER/.local/share/signal-api:/home/.local/share/signal-cli \\
        -e MODE=json-rpc \\
        docker.io/bbernhard/signal-cli-rest-api:latest

    ExecStop=/usr/bin/podman stop signal-cli-api

    [Install]
    WantedBy=default.target
    EOF
    ```

4. Create Service File for Signal MCP Client
    ```bash
    cat << EOF > "/home/$USER/.config/systemd/user/signal-mcp-client.service"
    [Unit]
    Description=Signal MCP Client Application
    After=network.target signal-cli-rest-api.service
    Wants=signal-cli-rest-api.service

    [Service]
    WorkingDirectory=/home/$USER/signal-mcp-client
    EnvironmentFile=/home/$USER/signal-mcp-client/.env
    SyslogIdentifier=signal-mcp-client

    Restart=on-failure
    RestartSec=30

    ExecStart=/home/$USER/.local/bin/uv run signal_mcp_client/main.py

    [Install]
    WantedBy=default.target
    EOF
    ```

5. Enable and Start the Services
    ```bash
    systemctl --user daemon-reload

    systemctl --user enable signal-cli-rest-api.service
    systemctl --user enable signal-mcp-client.service

    systemctl --user start signal-cli-rest-api.service
    systemctl --user start signal-mcp-client.service
    ```

6. Check Service Status and Logs
    ```bash
    systemctl --user status signal-cli-rest-api.service
    systemctl --user status signal-mcp-client.service

    journalctl --user -u signal-cli-rest-api.service -f
    journalctl --user -u signal-mcp-client.service -f
    ```