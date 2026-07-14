FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
ENV UV_LINK_MODE=copy

COPY . .
RUN uv sync && chmod +x entrypoint.sh scripts/*.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["silicon", "--help"]
