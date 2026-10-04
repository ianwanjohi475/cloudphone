# cloudphone "real phone" engine: the official Android Emulator running a
# Google Play system image, headless, with KVM acceleration.
#
# Why this engine exists next to Redroid:
#   * Google Play Store is built in and Google-certified (sign in and install
#     any Play app, no "device not certified" dance).
#   * x86_64 Play images from Android 11 on include Google's ARM translation,
#     so ARM-only apps install and run.
#   * The emulator has a real camera HAL. We point it at a v4l2loopback webcam
#     and pump uploaded photos/videos into it, so every app that opens the
#     camera sees the uploaded media. Redroid has no camera HAL at all.
#
# Needs /dev/kvm on the host. Build:  docker build -t cloudphone/emulator docker/emulator
FROM ubuntu:22.04

ARG API=33
ARG IMAGE_TAG=google_apis_playstore
ARG ABI=x86_64
ARG CMDLINE_TOOLS=11076708

ENV DEBIAN_FRONTEND=noninteractive \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk \
    API=${API} IMAGE_TAG=${IMAGE_TAG} ABI=${ABI}
ENV PATH=${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools:${ANDROID_SDK_ROOT}/emulator:${PATH}

RUN echo ">>> [1/3] installing system packages" \
    && apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless unzip curl ca-certificates socat ffmpeg v4l-utils procps \
        libpulse0 libgl1 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libasound2 \
        libxdamage1 libxkbfile1 libxrandr2 libdrm2 libgbm1 libx11-xcb1 libxcb1 libbsd0 \
    && rm -rf /var/lib/apt/lists/*

RUN echo ">>> [2/3] downloading Android command-line tools (~150 MB)" \
    && mkdir -p ${ANDROID_SDK_ROOT}/cmdline-tools \
    && curl -fSL --progress-bar -o /tmp/tools.zip \
       https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS}_latest.zip \
    && unzip -q /tmp/tools.zip -d ${ANDROID_SDK_ROOT}/cmdline-tools \
    && mv ${ANDROID_SDK_ROOT}/cmdline-tools/cmdline-tools ${ANDROID_SDK_ROOT}/cmdline-tools/latest \
    && rm /tmp/tools.zip

# Accepting the SDK licences is required to download the emulator and image.
# This is the long, quiet-looking step: about 2 GB. Progress lines below.
RUN yes | sdkmanager --licenses >/dev/null \
    && echo ">>> [3/3] downloading the Android emulator and Android ${API} with Google Play (~2 GB)" \
    && sdkmanager --install "platform-tools" "emulator" \
       "system-images;android-${API};${IMAGE_TAG};${ABI}" \
    && echo ">>> Android downloaded"

COPY entrypoint.sh camera-feed.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/camera-feed.sh

# 5555 = adb (forwarded from the emulator's loopback-only adb port)
EXPOSE 5555
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=240s --retries=5 \
  CMD test "$(adb -s emulator-5556 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
