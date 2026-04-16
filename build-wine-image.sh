#!/bin/bash
# 构建 Wine + PyInstaller 基础镜像并保存

set -e

echo "=== 构建镜像 ==="
docker build -t wine-pyinstaller-base .

echo "=== 保存镜像 ==="
docker save wine-pyinstaller-base | gzip > wine-pyinstaller-base.tar.gz

echo "=== 镜像已保存到 wine-pyinstaller-base.tar.gz ==="
docker images wine-pyinstaller-base

echo ""
echo "=== 使用示例 ==="
echo "# 加载镜像：docker load < wine-pyinstaller-base.tar.gz"
echo "# 打包程序：docker run --rm -v \$(pwd):/app -w /app wine-pyinstaller-base \\"
echo "    wine python3 -m PyInstaller --onefile --windowed your_app.py"
