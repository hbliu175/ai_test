# Dockerfile - Wine + PyInstaller for Windows EXE build
# 构建一次后保存镜像，以后可重复使用
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV WINEARCH=win64
ENV WINEDEBUG=-all

# 安装 Wine 和 Python
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wine64 \
        wine32 \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 安装 PyInstaller
RUN pip3 install --upgrade pip && \
    pip3 install pyinstaller

# 初始化 Wine
RUN wine --version

CMD ["/bin/bash"]
