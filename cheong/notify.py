"""알림: 이메일(SMTP) + macOS 데스크톱 알림.

config.yaml 예시:
  notify:
    desktop: true
    email:
      smtp_host: smtp.gmail.com
      smtp_port: 587
      username: you@gmail.com
      password: "앱 비밀번호 16자리"   # Gmail은 '앱 비밀번호' 사용 (일반 로그인 PW 아님)
      from_addr: you@gmail.com
      to_addr: you@gmail.com          # 받을 주소 (본인에게 보내면 됨)
"""
import smtplib
import subprocess
from email.mime.text import MIMEText


def _send_email(cfg, title, message):
    msg = MIMEText(message, _charset="utf-8")
    msg["Subject"] = title
    msg["From"] = cfg.get("from_addr", cfg["username"])
    msg["To"] = cfg["to_addr"]

    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(cfg["username"], cfg["password"])
        server.sendmail(msg["From"], [cfg["to_addr"]], msg.as_string())


def notify(config, title, message):
    ncfg = config.get("notify", {})

    # 1) 이메일
    email_cfg = ncfg.get("email", {})
    if email_cfg.get("username") and email_cfg.get("password") and email_cfg.get("to_addr"):
        try:
            _send_email(email_cfg, title, message)
            print(f"[notify] 이메일 전송 완료 → {email_cfg['to_addr']}")
        except Exception as e:  # noqa: BLE001
            print(f"[notify] 이메일 전송 실패: {e}")

    # 2) macOS 데스크톱 알림 (기본 on)
    if ncfg.get("desktop", True):
        safe_t = title.replace('"', "'")
        safe_m = message.replace('"', "'")
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe_m}" with title "{safe_t}" sound name "Glass"'],
                check=False,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[notify] 데스크톱 알림 실패: {e}")

    print(f"[notify] {title} — {message}")
