#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/zoeyzhou/Desktop/工作/风灵数据"

cd "$ROOT_DIR"

echo "========================================"
echo " 风灵看板一键更新发布"
echo " 项目目录: $ROOT_DIR"
echo "========================================"
echo

if [[ ! -x "./update_and_publish.sh" ]]; then
  chmod +x "./update_and_publish.sh"
fi

echo "[1/1] 执行 update_and_publish.sh ..."
echo

if ! ./update_and_publish.sh; then
  echo
  echo "执行失败。常见原因："
  echo "1) Git 身份未配置"
  echo "   git config user.name \"Zoey Zhou\""
  echo "   git config user.email \"你的GitHub邮箱@example.com\""
  echo "2) 网络问题导致 push 失败，可稍后重试"
  echo
  read -r -p "按回车键关闭窗口..."
  exit 1
fi

echo
echo "执行完成，线上链接："
echo "https://zoeyzhou111.github.io/fengling-dashboard/"
echo
read -r -p "按回车键关闭窗口..."
