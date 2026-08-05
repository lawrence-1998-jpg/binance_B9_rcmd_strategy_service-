"""审批人档鉴权 —— api/auth.py（ADR-003，2026-08-06）

为什么单独一个文件：各 blueprint 历史上各自复制了一份 require_api_key +
API_TOKENS（已知债，改 token 要五处一起改、咬过两次 401）。approver 档是新增
的第六种复制的机会——刻意不复制，放进这个无依赖的小模块，谁需要谁 import。
存量六份普通档暂不动（合并它们是另一件事，不该搭在本需求的车上）。

## approver 档是什么

页面 token 是"打开网页就拿得到"的（服务端注入进 HTML），因此**任何能改变生产
行为的动作都不能只认它**——否则任何打开页面的人都能批准架构变更/部署排序配置。
approver token 只存在于各机器的 config/.env，审批时由审批人手输，
永不写进 HTML / localStorage。

## fail-closed

API_TOKEN_APPROVER 未配置时返回 503 而不是放行："忘了配"必须表现为"谁都批
不了"，不能是"谁都能批"。与 8-05 的 VALID_API_KEYS 空值剔除同一原则。
"""
import os
from functools import wraps

from flask import jsonify, request

API_TOKEN_APPROVER = os.environ.get("API_TOKEN_APPROVER", "")


def require_approver(f):
    """只认 approver secret 的鉴权装饰器。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if not API_TOKEN_APPROVER:
            return jsonify({"error": "approver secret not configured",
                            "hint": "在 config/.env 配置 API_TOKEN_APPROVER 后重启服务"}), 503
        if key != API_TOKEN_APPROVER:
            return jsonify({"error": "Forbidden: approver secret required"}), 403
        return f(*args, **kwargs)
    return decorated
