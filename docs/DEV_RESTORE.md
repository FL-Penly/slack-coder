# 开发环境恢复指南

## 稳定版本

| Commit ID | 说明 |
|-----------|------|
| `b13cddf6c` | 最后稳定版本，Web UI 配置正常工作 |

## 恢复步骤

```bash
# 1. 恢复代码到指定 commit
git checkout b13cddf6c -- .
git clean -fd

# 2. 重新安装
uv tool install --force --editable .

# 3. 启动服务
slack-coder
```

## 完全重置（丢弃所有本地修改）

```bash
git reset --hard b13cddf6c
uv tool install --force --editable .
slack-coder
```

## 注意事项

- 配置文件在 `~/.vibe_remote/`，不会被 git 操作影响
- `slack-coder` 是原版命令，恢复后用这个启动
