# ws-scrcpy — browser-based scrcpy client for the phones.
# Serves the device screen + touch/keyboard over WebSocket on :8000.
FROM node:18-bullseye AS build

ARG WS_SCRCPY_REF=master
RUN apt-get update && apt-get install -y --no-install-recommends git android-tools-adb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 --branch ${WS_SCRCPY_REF} https://github.com/NetrisTV/ws-scrcpy.git
WORKDIR /opt/ws-scrcpy
RUN npm ci && npm run dist

FROM node:18-bullseye-slim
RUN apt-get update && apt-get install -y --no-install-recommends android-tools-adb \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/ws-scrcpy
COPY --from=build /opt/ws-scrcpy/dist ./dist
WORKDIR /opt/ws-scrcpy/dist
RUN npm ci --omit=dev || npm install --omit=dev

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENV AUTO_CONNECT=""
ENTRYPOINT ["/entrypoint.sh"]
