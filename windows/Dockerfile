# The Windows build environment (build_windows.sh): Debian 12 with MinGW-w64,
# so any Linux distro can cross-compile the Windows version. SDL2 for Windows
# is fetched by windows/build_in_env.sh (the official MinGW development
# release), so this image needs no rebuild when it changes.
FROM debian:12

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build pkg-config git ca-certificates curl \
        python3 python3-venv python3-pip perl xz-utils \
        gcc-mingw-w64-x86-64-posix g++-mingw-w64-x86-64-posix \
        binutils-mingw-w64-x86-64 mingw-w64-x86-64-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
