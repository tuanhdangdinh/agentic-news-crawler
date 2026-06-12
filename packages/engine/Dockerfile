FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "crawl_engine.service:app", "--host", "0.0.0.0", "--port", "8000"]
