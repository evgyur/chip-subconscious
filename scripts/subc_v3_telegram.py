#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

PROPOSAL_RE = re.compile(r"^prp_[a-f0-9]{16,64}$")
ACTION_BUTTONS = (
    ("✅ Accept", "a"),
    ("❌ Reject", "r"),
    ("⏭ Skip", "k"),
    ("💾 Save", "s"),
    ("🔕 Mute", "m"),
    ("🔎 Deep dive", "d"),
)


def callback_markup(proposal_instance_id: str) -> dict[str, Any]:
    if not PROPOSAL_RE.fullmatch(proposal_instance_id):
        raise ValueError("invalid proposal instance id")
    buttons = [
        {"text": label, "callback_data": f"subcv3:{code}:{proposal_instance_id}"}
        for label, code in ACTION_BUTTONS
    ]
    return {"inline_keyboard": [buttons[:2], buttons[2:5], buttons[5:]]}


def validate_single_suggestion(text: str) -> None:
    """Fail closed if one Telegram message contains zero or multiple proposals."""
    required_blocks = (
        r"(?m)^➊\s+\S",
        r"(?m)^┈ почему сейчас:\s+\S",
        r"(?m)^┈ ценность:\s+\S",
        r"(?m)^┈ effort / risk / confidence:\s+\S",
        r"(?m)^┈ дешёвый тест:\s+\S",
        r"(?m)^┈ выбери действие кнопкой ниже\s*$",
    )
    has_secondary_marker = bool(re.search(r"(?m)^[➋➌➍➎➏➐➑➒]\s+\S", text))
    if has_secondary_marker or any(len(re.findall(pattern, text)) != 1 for pattern in required_blocks):
        raise ValueError("Telegram proposal must contain exactly one suggestion")


def parse_target(target: str) -> tuple[str, int | None]:
    match = re.fullmatch(r"telegram:(-?\d+)(?::(\d+))?", target.strip())
    if not match:
        raise ValueError("expected telegram:<chat_id>[:thread_id]")
    return match.group(1), int(match.group(2)) if match.group(2) else None


def _token(env_file: str | Path | None = None) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    path = Path(env_file).expanduser() if env_file else Path.home() / ".hermes/.env"
    if not token and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() == "TELEGRAM_BOT_TOKEN":
                    token = value.strip().strip('"').strip("'")
                    break
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN unavailable")
    return token


def _api_call(token: str, method: str, payload: dict[str, Any], opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    encoded = urllib.parse.urlencode({
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        for key, value in payload.items() if value is not None
    }).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with opener(request, timeout=20) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            failure = json.loads(exc.read().decode())
        except Exception:
            failure = {}
        description = str(failure.get("description") or "")
        if method == "editMessageReplyMarkup" and "message is not modified" in description.lower():
            return {
                "ok": True,
                "unchanged": True,
                "result": {
                    "message_id": int(payload.get("message_id") or 0),
                    "reply_markup": payload.get("reply_markup"),
                },
            }
        raise RuntimeError(f"Telegram {method} failed: HTTP {exc.code}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed")
    return result


def verify_bot(token: str, expected_username: str = "") -> dict[str, Any]:
    result = _api_call(token, "getMe", {})["result"]
    username = str(result.get("username") or "")
    if expected_username and username.lower() != expected_username.lstrip("@").lower():
        raise RuntimeError("Telegram bot identity mismatch")
    return {"id": result.get("id"), "username": username}


def apply_markup(
    *,
    token: str,
    target: str,
    proposal_instance_id: str,
    text: str | None = None,
    message_id: int | None = None,
) -> dict[str, Any]:
    chat_id, thread_id = parse_target(target)
    markup = callback_markup(proposal_instance_id)
    if message_id is None:
        if not text:
            raise ValueError("text is required for send")
        validate_single_suggestion(text)
        result = _api_call(token, "sendMessage", {
            "chat_id": chat_id,
            "message_thread_id": thread_id,
            "text": text[:3900],
            "reply_markup": markup,
        })
    else:
        result = _api_call(token, "editMessageReplyMarkup", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": markup,
        })
    message = result.get("result") or {}
    return {
        "ok": True,
        "message_id": int(message.get("message_id") or message_id or 0),
        "button_count": sum(len(row) for row in markup["inline_keyboard"]),
        "proposal_instance_id": proposal_instance_id,
        "unchanged": bool(result.get("unchanged", False)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Send or repair SUBCONSCIOUS v3 Telegram proposals with inline buttons")
    parser.add_argument("action", choices=("send", "attach"))
    parser.add_argument("--target", required=True)
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--text-file")
    parser.add_argument("--message-id", type=int)
    parser.add_argument("--expected-bot-username", default=os.environ.get("SUBC_V3_EXPECTED_BOT_USERNAME", ""))
    parser.add_argument("--token-env-file")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.action == "send" and not args.text_file:
        parser.error("send requires --text-file")
    if args.action == "attach" and not args.message_id:
        parser.error("attach requires --message-id")
    token = _token(args.token_env_file)
    bot = verify_bot(token, args.expected_bot_username)
    text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else None
    receipt = apply_markup(
        token=token,
        target=args.target,
        proposal_instance_id=args.proposal_id,
        text=text,
        message_id=args.message_id,
    )
    receipt["bot_username"] = bot["username"]
    if args.output:
        Path(args.output).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
