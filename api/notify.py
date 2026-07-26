"""
邮件通知 —— 目前只用于「Tell Lawrence More」反馈提交后的即时通知。

2026-07-26：Lawrence 要求"如果真的产生了数据，及时推送到我的邮箱"。

设计：
- 通用 SMTP 实现（不绑定某一家邮件服务商），走标准 587 端口 + STARTTLS。
  配置齐全就发，任何一项缺失就跳过发送——**反馈本身必须先落库成功**，
  邮件通知是锦上添花，绝不能因为邮件发不出去就让用户的反馈提交失败。
- 失败只记日志，不抛异常给调用方。
- 图片附件直接嵌进邮件（而不是发一个需要鉴权才能打开的链接），收信人在
  邮件客户端里点开就能看，不需要再登录系统。

需要的环境变量（写进 config/.env，缺一项就不发信，只记日志）：
    SMTP_HOST       SMTP 服务器地址
    SMTP_PORT       端口（默认 587，STARTTLS）
    SMTP_USER       登录用户名
    SMTP_PASSWORD   登录密码 / 应用专用密码
    SMTP_FROM       发件人地址（不填则用 SMTP_USER）
    FEEDBACK_NOTIFY_EMAIL  收件人（不填则默认 lawrence.zzz@binance.com）
"""
import logging
import mimetypes
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

DEFAULT_NOTIFY_EMAIL = "lawrence.zzz@binance.com"


def _smtp_config() -> dict | None:
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    if not (host and user and password):
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "user": user,
        "password": password,
        "from_addr": os.environ.get("SMTP_FROM", "").strip() or user,
        "to_addr": os.environ.get("FEEDBACK_NOTIFY_EMAIL", "").strip() or DEFAULT_NOTIFY_EMAIL,
    }


def notify_feedback(feedback_id: int, category: str, content: str,
                    page_context: str, image_bytes: bytes | None = None,
                    image_filename: str | None = None) -> bool:
    """反馈落库成功后调用。返回 True 表示邮件确认发出（供调用方记 notified_at）。

    没配置 SMTP 时直接返回 False（不算错误，只是没开这个功能）；
    配置了但发送失败时记 warning 日志并返回 False——绝不向上抛异常，
    因为这个函数是在"反馈已经落库"之后调用的收尾动作，不该反过来影响主流程。
    """
    cfg = _smtp_config()
    if cfg is None:
        logger.info("SMTP 未配置，跳过反馈邮件通知（反馈本身已正常落库，id=%s）", feedback_id)
        return False

    msg = EmailMessage()
    msg["Subject"] = f"[B9反馈] {category} · #{feedback_id}"
    msg["From"] = cfg["from_addr"]
    msg["To"] = cfg["to_addr"]
    body = (
        f"B9 工作台收到一条新反馈。\n\n"
        f"类别：{category}\n"
        f"页面：{page_context or '（未记录）'}\n"
        f"内容：\n{content}\n\n"
        f"—— 反馈 ID #{feedback_id}，来自 Tell Lawrence More 模块（自动发送，无需回复）"
    )
    msg.set_content(body)

    if image_bytes:
        ctype, _ = mimetypes.guess_type(image_filename or "image.png")
        maintype, subtype = (ctype or "image/png").split("/", 1)
        msg.add_attachment(image_bytes, maintype=maintype, subtype=subtype,
                           filename=image_filename or "attachment.png")

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
        logger.info("反馈邮件通知已发送 id=%s → %s", feedback_id, cfg["to_addr"])
        return True
    except Exception as e:
        logger.warning("反馈邮件通知发送失败（不影响反馈已落库）id=%s: %s", feedback_id, e)
        return False
