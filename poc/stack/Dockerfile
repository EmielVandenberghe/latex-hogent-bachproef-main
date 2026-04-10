FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir prometheus_client requests urllib3 pysnmp==4.4.12 pyasn1==0.4.8

COPY incontrol2_exporter.py .

EXPOSE 8080

CMD ["python", "-u", "incontrol2_exporter.py"]
