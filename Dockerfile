FROM node:20-bookworm-slim AS frontend-build
WORKDIR /workspace/frontend
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY backend/requirements.txt /workspace/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ /workspace/backend/
COPY --from=frontend-build /workspace/frontend/build /workspace/frontend/build
# Pinned stable TLC release, verified against the checksum published by tlaplus.
RUN mkdir -p /opt/tla && curl -fLSs --retry 3 -o /opt/tla/tla2tools.jar https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar \
    && echo 'bee4a54f3ee3d4afc347c3240ec2d9e93b075104  /opt/tla/tla2tools.jar' | sha1sum -c -
ENV TLC_JAR=/opt/tla/tla2tools.jar
# Never run submitted TLA+ models in this public web container.
ENV TLC_EXECUTION_ENABLED=0
ENV PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["sh","-c","cd /workspace/backend && exec waitress-serve --host=0.0.0.0 --port=${PORT:-10000} app:app"]
