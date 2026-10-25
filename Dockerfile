FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY roomprint ./roomprint
COPY web ./web
COPY demo ./demo
ENV ROOMPRINT_DATA=/tmp/roomprint
EXPOSE 8000
CMD ["sh", "-c", "uvicorn roomprint.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
