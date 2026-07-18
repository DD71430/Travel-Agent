FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000

FROM base AS dev
COPY main.py .
COPY travel_agent ./travel_agent
CMD ["uvicorn", "travel_agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
COPY main.py .
COPY travel_agent ./travel_agent
CMD ["uvicorn", "travel_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
