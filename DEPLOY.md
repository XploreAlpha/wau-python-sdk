# wau-python-sdk 部署(PyPI 发布)

wau-python-sdk 是 **Python package**,无独立部署。B 端开发者 `pip install` 后 import。

## 发布流程

```bash
# 1. 打 tag(用户手动,per [[feedback-cli-cant-push-git]])
git tag v1.1.0
git push origin v1.1.0

# 2. PyPI 发布(用户手动 twine upload)
python -m build
twine upload dist/*
```

## 版本兼容性

- **v1.1.x** ↔ wau-llm-router v0.9.x
- **wire 100% 兼容** v0.8.0

## 配置

```python
bot = Bot(
    token=os.environ["TELEGRAM_BOT_TOKEN"],  # env 占位
    tenant_id="acme",
    address="127.0.0.1:18431",  # wau-channel webhook
)
```

**所有 token 用 `$VAR` 占位**(per 双 feedback)

## 升级路径

- v1.1.0 → v1.0.x:wire 100% 兼容
- v1.1.0 → v1.2.0(roadmap):
  - async streaming bot helper
  - pip wheels 跨平台(linux/macos/windows)
