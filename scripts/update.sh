#!/usr/bin/env bash
# ============================================================================
# 滨海小镇 - 手动更新脚本
# 从 GitHub 拉取最新代码，安全更新项目文件
# 用法: bash scripts/update.sh
# ============================================================================

set -euo pipefail

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- 项目根目录（脚本所在目录的上一级） ----
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     滨海小镇 - 手动更新脚本                 ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo -e "${YELLOW}项目目录:${NC} $APP_ROOT"
echo ""

# ---- 检查 git ----
if ! command -v git &>/dev/null; then
    echo -e "${RED}[错误] 未检测到 git，请先安装 git${NC}"
    exit 1
fi

cd "$APP_ROOT"

# ---- 检查是否为 git 仓库 ----
if [ ! -d ".git" ]; then
    echo -e "${RED}[错误] 当前目录不是 git 仓库，无法使用此方式更新${NC}"
    echo -e "${YELLOW}提示:${NC} 请手动下载 https://github.com/kute0213/bhxz 的代码替换"
    exit 1
fi

# ---- 检查是否有未提交的更改 ----
if ! git diff --quiet HEAD; then
    echo -e "${YELLOW}[警告] 存在未提交的本地修改：${NC}"
    git status --short
    echo ""
    echo -e "${YELLOW}是否继续？未提交的修改可能被覆盖。${NC}"
    read -r -p "继续更新？(y/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${RED}已取消更新${NC}"
        exit 0
    fi
    # 暂存本地修改，更新后尝试恢复
    STASH_NEEDED=true
    git stash --include-untracked || true
    echo -e "${YELLOW}本地修改已暂存，更新后可执行 'git stash pop' 恢复${NC}"
else
    STASH_NEEDED=false
fi

echo ""
echo -e "${CYAN}[1/3] 正在获取远程更新...${NC}"

# ---- 获取远程更新 ----
if ! git fetch --all --tags --force 2>&1; then
    echo -e "${RED}[错误] git fetch 失败，请检查网络连接${NC}"
    if [ "$STASH_NEEDED" = true ]; then
        git stash pop || true
    fi
    exit 1
fi

echo -e "${GREEN}✓ 远程更新获取成功${NC}"
echo ""

# ---- 查看更新内容 ----
echo -e "${CYAN}[2/3] 更新内容预览：${NC}"
BEFORE_HASH=$(git rev-parse HEAD)
AFTER_HASH=$(git rev-parse origin/main)

if [ "$BEFORE_HASH" = "$AFTER_HASH" ]; then
    echo -e "${GREEN}✓ 当前已是最新版本，无需更新${NC}"
    if [ "$STASH_NEEDED" = true ]; then
        git stash pop || true
    fi
    exit 0
fi

echo -e "  当前版本: ${YELLOW}$(echo "$BEFORE_HASH" | head -c 8)${NC}"
echo -e "  最新版本: ${GREEN}$(echo "$AFTER_HASH" | head -c 8)${NC}"
echo ""
echo -e "${YELLOW}--- 最近提交 ---${NC}"
git log --oneline "$BEFORE_HASH..origin/main" | head -20 || true
echo ""

# ---- 确认更新 ----
read -r -p "确认应用以上更新？(Y/n): " confirm
if [[ "$confirm" == "n" || "$confirm" == "N" ]]; then
    echo -e "${YELLOW}已取消更新${NC}"
    if [ "$STASH_NEEDED" = true ]; then
        git stash pop || true
    fi
    exit 0
fi

# ---- 应用更新 ----
echo ""
echo -e "${CYAN}[3/3] 正在应用更新...${NC}"

if ! git reset --hard origin/main 2>&1; then
    echo -e "${RED}[错误] 更新失败，请手动解决冲突${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 代码已更新到最新版本${NC}"
echo ""

# ---- 恢复暂存 ----
if [ "$STASH_NEEDED" = true ]; then
    echo -e "${YELLOW}正在恢复本地暂存的修改...${NC}"
    git stash pop || true
fi

# ---- 完成 ----
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     更新完成！                                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo -e "${YELLOW}提示:${NC} 请重启服务器使新代码生效"
echo -e "${YELLOW}提示:${NC} 如果遇到 Python 依赖变化，请执行: pip install -r requirements.txt"
echo ""