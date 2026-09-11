FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --home-dir /home/user --uid 10001 movie-agent \
    && mkdir -p /home/user/app/projects \
    && chown -R movie-agent:movie-agent /home/user/app

COPY --chown=movie-agent:movie-agent agent agent
COPY --chown=movie-agent:movie-agent server server
COPY --chown=movie-agent:movie-agent prompts prompts
COPY --chown=movie-agent:movie-agent workflows workflows
COPY --chown=movie-agent:movie-agent web web
COPY --chown=movie-agent:movie-agent app.py .

USER movie-agent

# Expose ModelScope Studio required port 7860
EXPOSE 7860

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "7860"]
