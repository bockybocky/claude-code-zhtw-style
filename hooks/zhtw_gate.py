#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop hook：回話送出前掃「整句英文」與「簡體字」。

為什麼有這支（使用者回報「你又開始說英文了」）：
規則早就寫在回話風格檔第一條（整篇繁體中文），但規則存在擋不住規則被跳過。
修法：把規則做成送出前的機械檢查。

判定（保守，寧可漏抓不要誤擋）：
  1. 英文句：一行裡連續 ≥6 個英文單字，且該段不在反引號、網址、檔案路徑、引號（「」“”""）內。
     股票代號、指令、路徑、引用原文都是合法的，所以先把這些挖掉再數。
  2. 簡體字：命中常見簡體字表（約 60 字，寧可漏抓不要誤擋）；
     同樣先挖掉引號內（引簡體原文加註是合法的）。
防無限迴圈：stop_hook_active 為真時放行。
退出碼：0 放行；2 擋下並把原因印到 stderr。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SIMP = set("开关状决软资仓应变报过运点对术后来们说这个东乐为习无内产电视话见谢让认识论长门问发现该会师义还没经济业机构与时间样题实单价级别数据发现")
INLINE_CODE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+|www\.\S+")
PATH = re.compile(r"(?:[A-Za-z]:[\\/]|~/|/[\w.\-]+/)[\w.\-\\/（）()]*")
NEWLINE = chr(10)
QUOTED = re.compile(r"「[^」]*」|“[^”]*”|\"[^\"\n]*\"|『[^』]*』")
EN_RUN = re.compile(r"(?:\b[A-Za-z][A-Za-z'’\-]*\b[\s,;:]*){6,}")


def scrub(line: str) -> str:
    for pat in (INLINE_CODE, URL, PATH, QUOTED):
        line = pat.sub(" ", line)
    return line


def collect_turn_text(payload: dict) -> str:
    """回這一輪助理講過的所有文字（含中途的進度短句）。

    讀不到逐字檔就退回只看最後一則——寧可少抓，不要因為閘自己壞掉而擋住回話。
    """
    fallback = payload.get("last_assistant_message") or ""
    path = payload.get("transcript_path")
    if not path:
        return fallback
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fallback

    chunks: list[str] = []
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
            break
        if role != "assistant":
            continue
        content = (row.get("message") or {}).get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(str(block.get("text") or ""))
    if not chunks:
        return fallback
    return NEWLINE.join(reversed(chunks))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # fail-open
        print(f"[zhtw_gate] 讀不到輸入，放行：{exc}", file=sys.stderr)
        return 0
    if payload.get("stop_hook_active"):
        return 0
    # 使用者回報「怎麼又講英文了」：原本只看整輪最後一則，
    # 而那天的英文全出現在中途的進度短句上，閘根本沒看到那些字。
    # 改成掃「這一輪」——從最後一則使用者訊息之後的每一則助理訊息。
    message = collect_turn_text(payload)
    if not message.strip():
        return 0

    problems: list[str] = []
    in_fence = False
    for no, raw in enumerate(message.splitlines(), 1):
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or raw.lstrip().startswith(("    ", "\t")):
            continue  # 程式碼區塊與縮排碼不掃
        line = scrub(raw)
        m = EN_RUN.search(line)
        if m and len(m.group(0).split()) >= 6:
            problems.append(f"line {no}: 整句英文 → {m.group(0).strip()[:80]}")
        simp = sorted({c for c in line if c in SIMP})
        if simp:
            problems.append(f"line {no}: 簡體字 {''.join(simp)} → {raw.strip()[:60]}")

    if not problems:
        return 0
    print(
        "回話沒過繁中機械檢查（回話風格第二條：整篇繁體中文、不夾英文句）：\n"
        + "\n".join(problems[:8])
        + "\n\n修法：把英文句改成中文（股票代號、指令、路徑、引用原文可留原樣，旁邊補一句中文）；"
          "簡體字改繁體。改好再收尾。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
