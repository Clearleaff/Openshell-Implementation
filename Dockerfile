FROM python:3.12-slim-bookworm
RUN groupadd -g 10001 agent && useradd -m -u 10001 -g 10001 agent && mkdir -p /run/agent-config /workspace /app && chown -R agent:agent /run/agent-config /workspace /app
RUN echo SYNTHETIC_CANARY_NO_SECRET > /opt/blocked-canary && chmod 444 /opt/blocked-canary
COPY --chown=agent:agent app /app/app
RUN chown -R agent:agent /app && chmod -R 775 /app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
CMD ["sleep", "infinity"]
