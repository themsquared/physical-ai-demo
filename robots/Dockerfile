FROM python:3.12-slim
WORKDIR /app
COPY robots/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY robots /app/robots
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "robots.server"]
