#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse hook：工具執行前，檢查「剛剛那句進度短句」是不是英文。

為什麼要有這支（2026-09-04，使用者一天內抓到三次「你又講英文了」）：
既有的 zhtw_gate.py 掛在 Stop 事件，只在整輪要收尾時才跑。
中途的進度短句在螢幕上出現的當下沒有任何東西看它，
所以同一輪裡可以一邊修這個毛病一邊再犯——當天實際發生。

實驗發現（本機逐字檔實測）：進度短句與工具呼叫是**兩列**，
而且文字那列**先寫進逐字檔**。所以 PreToolUse 這個時機看得到那句話。
擋不住它被顯示，但擋得住下一個動作，等於當場踩剎車。

一句話一次警告：擋過的句子記進 state 檔，不會同一句擋到天荒地老。
沒有這條就會死鎖——違規的句子留在逐字檔裡，下一個工具照樣被它擋。

判定沿用 zhtw_gate.py 的同一套（保守：連六個英文單字、先挖掉程式碼與路徑）。
退出碼 0 放行；2 擋下並把理由送回模型。
任何例外一律放行——閘自己壞掉不該擋住工作。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

STATE = Path.home() / ".claude" / "hooks" / ".zhtw_live_state.json"
STATE_KEEP = 200          # 最多記幾筆擋過的句子
SIMP = set("开关状决软资仓应变报过运点对术后来们说这个东乐为习无内产电视话见谢让认识论长门问发现该会师义还没经济业机构与时间样题实单价级别数据")
INLINE_CODE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+|www\.\S+")
PATH = re.compile(r"(?:[A-Za-z]:[\\/]|~/|/[\w.\-]+/)[\w.\-\\/（）()]*")
QUOTED = re.compile(r"「[^」]*」|“[^”]*”|\"[^\"\n]*\"|『[^』]*』")
EN_RUN = re.compile(r"(?:\b[A-Za-z][A-Za-z'’\-]*\b[\s,;:]*){6,}")


def scrub(line: str) -> str:
    for pat in (INLINE_CODE, URL, PATH, QUOTED):
        line = pat.sub(" ", line)
    return line


def offences(message: str) -> list[str]:
    problems: list[str] = []
    in_fence = False
    for no, raw in enumerate(message.splitlines(), 1):
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or raw.lstrip().startswith(("    ", "\t")):
            continue
        line = scrub(raw)
        hit = EN_RUN.search(line)
        if hit and len(hit.group(0).split()) >= 6:
            problems.append(f"整句英文 → {hit.group(0).strip()[:70]}")
        simp = sorted({c for c in line if c in SIMP})
        if simp:
            problems.append(f"簡體字 {''.join(simp)} → {raw.strip()[:50]}")
    return problems


def latest_narration(path: str) -> str:
    """回這一輪最後一則助理文字。碰到使用者訊息就停，避免翻到上一輪。"""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        role = row.get("type") or (row.get("message") or {}).get("role")
        if role == "user":
            return ""
        if role != "assistant":
            continue
        content = (row.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            texts = [str(b.get("text") or "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(t for t in texts if t.strip())
            if joined.strip():
                return joined
    return ""


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"seen": []}


def save_state(state: dict) -> None:
    try:
        state["seen"] = state.get("seen", [])[-STATE_KEEP:]
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    path = payload.get("transcript_path")
    if not path:
        return 0
    try:
        text = latest_narration(path)
        if not text.strip():
            return 0
        problems = offences(text)
        if not problems:
            return 0
        digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]
        state = load_state()
        if digest in state.get("seen", []):
            return 0          # 同一句只擋一次，不然會死鎖
        state.setdefault("seen", []).append(digest)
        state["last"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "problems": problems[:3]}
        save_state(state)
    except Exception:  # noqa: BLE001
        return 0

    print(
        "你剛剛那句進度短句沒過繁中檢查（回話風格第二條：每一則訊息都要繁體中文，"
        "包含工具之間的進度短句）：\n"
        + "\n".join(f"  - {p}" for p in problems[:5])
        + "\n\n現在用中文把那句重講一次，再繼續做事。同一句只會擋你一次。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
