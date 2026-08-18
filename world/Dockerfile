FROM python:3.12-slim
WORKDIR /app
COPY world/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY world /app/world
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "world.app:app", "--host", "0.0.0.0", "--port", "8080"]
