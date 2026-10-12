FROM python:3.12-slim-bookworm
ARG BUILD_VERSION=0.1.0
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="addon" io.hass.arch="amd64"
ENV PYTHONUNBUFFERED=1 TZ=Europe/Berlin
RUN apt-get update && apt-get install -y --no-install-recommends firefox-esr ca-certificates tzdata curl && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://github.com/mozilla/geckodriver/releases/download/v0.36.0/geckodriver-v0.36.0-linux64.tar.gz | tar -xz -C /usr/bin geckodriver && chmod +x /usr/bin/geckodriver
RUN pip install --no-cache-dir flask==3.1.1 selenium==4.34.2
WORKDIR /app
COPY app.py /app/app.py
CMD ["python", "/app/app.py"]
