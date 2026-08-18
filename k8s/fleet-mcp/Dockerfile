FROM python:3.12-slim
WORKDIR /app
COPY k8s/fleet-mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY k8s/fleet-mcp/app.py .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "app.py"]
