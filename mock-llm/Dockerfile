FROM python:3.12-slim
WORKDIR /app
COPY mock-llm/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mock-llm /app/mock_llm
ENV PYTHONUNBUFFERED=1
EXPOSE 8200
CMD ["uvicorn", "mock_llm.app:app", "--host", "0.0.0.0", "--port", "8200"]
