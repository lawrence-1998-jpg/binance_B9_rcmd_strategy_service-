---
name: flask-blueprint-syspath-gotcha
description: 用 python3 path/to/script.py 直接跑时 sys.path 不含项目根，跨包 import 会 ModuleNotFoundError
metadata: 
  node_type: memory
  type: reference
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-25T22:43:34.326Z
---

通用 Python 部署坑（不限于 B9 项目），2026-07-26 在 Flask 生产服务上踩过：

当用 `python3 api/server.py`（无论是手动、run.sh 脚本、还是 systemd `ExecStart`）
直接运行一个脚本文件时，Python 只把**脚本自身所在的目录**（这里是 `api/`）加进
`sys.path[0]`，**不会**自动加入当前工作目录或脚本的上级目录。

**症状**：
- 同目录模块 `from other_module_in_same_dir import x` —— 能工作（同目录天然在 path 里）
- 包路径写法 `from api.other_module import x` —— 失败，`ModuleNotFoundError: No module named 'api'`（这里没有一个叫 `api` 的可导入包）
- 跨目录 `from sibling_package import x`（比如从 `api/` 导入 `crawler/` 下的模块）—— 同样失败，`ModuleNotFoundError: No module named 'crawler'`

**修复**：在入口脚本最开头（其它 import 之前）显式把项目根目录塞进 `sys.path`：
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```
（`dirname` 用几次取决于入口脚本离项目根几层）

**How to apply**：以后写任何"多个开发者/agent 各自交付一个模块，最后拼到同一个
Flask/Django/FastAPI 入口"的项目，先确认清楚入口是怎么启动的（`-m` 模块方式 vs
直接跑文件路径），跨模块 import 写法要匹配启动方式，否则本地测试永远看不出这个
问题（本地测试常常是从项目根用 `-m` 方式跑，只有生产 systemd 直接跑文件路径才
会暴露）。
