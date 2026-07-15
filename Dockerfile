# W0Guard testnet node -- minimal client image.
#
# Only external dependency across the whole client stack is
# `websockets` (confirmed by inspecting every import in
# w0guard_node.py / networked_node.py / node_transport.py /
# core_engine.py / leukocyte_protocol.py / erythrocyte.py -- everything
# else is Python stdlib).
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir websockets

# Only the six files the client actually needs -- NOT bootstrap_relay.py
# (that's server-side only) and not the rest of the repo.
COPY w0guard_node.py networked_node.py node_transport.py core_engine.py leukocyte_protocol.py erythrocyte.py ./

# node_config.json (created on first run) and the per-node audit log
# both get written here -- mount a volume at /app if you want them to
# survive `docker compose down` / container recreation (see
# docker-compose.yml, which does this by default).

# Needs a real TTY + stdin for the interactive first-time setup and the
# attack/status/quit console -- run with `docker run -it` or
# `docker compose run` (compose file below sets stdin_open/tty).
CMD ["python3", "w0guard_node.py"]
