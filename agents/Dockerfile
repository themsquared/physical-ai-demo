FROM python:3.12-slim
WORKDIR /app
COPY agents/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY agents /app/agents
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "agents.cognition"]
