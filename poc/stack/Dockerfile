FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir prometheus_client requests pysnmp

COPY incontrol2_exporter.py .

EXPOSE 8080

CMD ["python", "-u", "incontrol2_exporter.py"]
