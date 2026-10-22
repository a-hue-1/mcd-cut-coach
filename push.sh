#!/usr/bin/env bash
# 在 GitHub 网页建好空的公开仓库 mcd-cut-coach 后，运行本脚本推送代码。
#   用法：bash push.sh
set -e

REPO_URL="https://github.com/a-hue-1/mcd-cut-coach.git"

echo "==> 配置远端"
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"

echo "==> 切换到 main 分支"
git branch -M main

echo "==> 推送"
git push -u origin main

echo
echo "==> 完成！仓库地址：$REPO_URL"
echo "==> 接下来：在该仓库确认 5 个强制文件齐全，然后到赛事仓库提交报名 Issue"
echo "    https://github.com/M-China/mcd-developer-innovation-challenge/issues"
