#!/bin/bash
# Tailwind CSS 构建脚本
# 用法: bash .trae/build-tailwind.sh
# 作用: 扫描 templates/ 和 static/js/ 下的文件，生成生产环境静态 CSS 文件

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "[Tailwind] 正在构建 CSS..."

# 检查 .trae/node_modules 中是否有 tailwindcss
if [ ! -f ".trae/node_modules/.bin/tailwindcss" ]; then
    echo "[Tailwind] 未检测到 tailwindcss，正在安装..."
    cd .trae && npm install tailwindcss@3 && cd ..
fi

# 生成生产环境 CSS（压缩、仅包含用到的类）
npx --prefix .trae tailwindcss \
  -c .trae/tailwind.config.js \
  -i .trae/tailwind-source.css \
  -o static/css/tailwind.css \
  --minify

echo "[Tailwind] 构建完成 → static/css/tailwind.css"