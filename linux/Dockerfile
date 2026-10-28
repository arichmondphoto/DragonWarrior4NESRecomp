# The Linux build environment (build_linux.sh): Debian 12, so the AppImage
# runs on distros with glibc 2.36 or newer (2022 onward), whatever distro
# builds it. SDL2 is built from source with every desktop backend (X11,
# Wayland, PipeWire, PulseAudio, ALSA, controllers), each loaded at run time,
# so one AppImage adapts to the player's desktop and sound system.
FROM debian:12

ARG SDL_VERSION=2.30.12
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build pkg-config git ca-certificates curl \
        python3 python3-venv python3-pip perl file patchelf xz-utils desktop-file-utils \
        libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxi-dev libxss-dev \
        libxfixes-dev libxinerama-dev libxkbcommon-dev \
        libwayland-dev wayland-protocols libdecor-0-dev \
        libegl-dev libgl-dev libgles-dev libdrm-dev libgbm-dev \
        libpulse-dev libasound2-dev libpipewire-0.3-dev \
        libudev-dev libdbus-1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/libsdl-org/SDL/releases/download/release-${SDL_VERSION}/SDL2-${SDL_VERSION}.tar.gz" \
        -o /tmp/sdl.tar.gz \
    && tar -xzf /tmp/sdl.tar.gz -C /tmp \
    && cmake -S /tmp/SDL2-${SDL_VERSION} -B /tmp/sdl-build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/sdl2 \
        -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TEST=OFF \
        -DSDL_X11=ON -DSDL_WAYLAND=ON -DSDL_WAYLAND_LIBDECOR=ON -DSDL_KMSDRM=ON \
        -DSDL_PIPEWIRE=ON -DSDL_PULSEAUDIO=ON -DSDL_ALSA=ON -DSDL_JACK=OFF \
        -DSDL_OPENGL=ON -DSDL_OPENGLES=ON \
    && cmake --build /tmp/sdl-build \
    && cmake --install /tmp/sdl-build \
    && rm -rf /tmp/sdl.tar.gz /tmp/SDL2-${SDL_VERSION} /tmp/sdl-build

ENV SDL2_DIR=/opt/sdl2/lib/cmake/SDL2
WORKDIR /src
