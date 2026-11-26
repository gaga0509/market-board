#!/usr/bin/env python3
"""抓取市場資料並寫入 data.json。

用法:  pip install requests && python fetch_data.py
建議每天收盤後（晚上 9:30 之後，融資資料才會更新）執行一次。
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).with_name("data.json")
DAYS = 75  # 台股資料回溯的日曆天數
UA = {"User-Agent": "Mozilla/5.0 (market-board)"}
TW = timezone(timedelta(hours=8))


def num(s):
    """'1,234,567' -> 1234567.0"""
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


# ---------- Yahoo Finance：原油 / 匯率 / VIX ----------
def yahoo(symbol, rng="6mo"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    for attempt in range(4):
        r = requests.get(url, params={"range": rng, "interval": "1d"}, headers=UA, timeout=20)
        if r.status_code == 200:
            break
        time.sleep(3 * (attempt + 1))
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    offset = res["meta"].get("gmtoffset", 0)
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for ts, c in zip(res["timestamp"], closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + offset, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append([d, round(c, 4)])
    return out


# ---------- 證交所：三大法人買賣超 ----------
def fetch_institutional(day):
    url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
    r = requests.get(url, params={"type": "day", "dayDate": day, "response": "json"},
                     headers=UA, timeout=20)
    j = r.json()
    if j.get("stat") != "OK" or not j.get("data"):
        return None
    foreign = trust = dealer = total = 0.0
    for row in j["data"]:
        name, diff = row[0], num(row[3])
        if diff is None:
            continue
        if "合計" in name:
            total = diff
        elif "外資" in name:
            foreign += diff
        elif "投信" in name:
            trust += diff
        elif "自營商" in name:
            dealer += diff
    to_yi = lambda v: round(v / 1e8, 2)  # 元 -> 億元
    return {"foreign": to_yi(foreign), "trust": to_yi(trust),
            "dealer": to_yi(dealer), "total": to_yi(total)}


# ---------- 證交所：融資餘額 ----------
def fetch_margin(day):
    url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    r = requests.get(url, params={"date": day, "selectType": "MS", "response": "json"},
                     headers=UA, timeout=20)
    j = r.json()
    if j.get("stat") != "OK":
        return None
    tables = j.get("tables") or []
    rows = [row for t in tables for row in t.get("data", [])]
    rows += j.get("creditList", [])  # 舊格式備援
    for row in rows:
        if "融資金額" in str(row[0]):
            v = num(row[-1])  # 今日餘額，單位：仟元
            if v is not None:
                return round(v / 1e5, 2)  # -> 億元
    return None


def main():
    data = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    data.setdefault("institutional", {})
    data.setdefault("margin", {})

    # 全球資料：每次整段覆蓋
    for key, sym in [("wti", "CL=F"), ("brent", "BZ=F"), ("usdtwd", "TWD=X"), ("vix", "^VIX")]:
        try:
            data[key] = yahoo(sym)
            print(f"OK   {key}: {len(data[key])} 筆")
        except Exception as e:
            print(f"FAIL {key}: {e}")

    # 台股資料：只補缺的日期
    today = datetime.now(TW).date()
    for i in range(DAYS, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        day, iso = d.strftime("%Y%m%d"), d.isoformat()
        try:
            if iso not in data["institutional"]:
                v = fetch_institutional(day)
                time.sleep(0.8)
                if v:
                    data["institutional"][iso] = v
                    print(f"OK   法人 {iso}")
            if iso not in data["margin"]:
                v = fetch_margin(day)
                time.sleep(0.8)
                if v is not None:
                    data["margin"][iso] = v
                    print(f"OK   融資 {iso}")
        except Exception as e:
            print(f"FAIL {iso}: {e}")
            time.sleep(3)

    data["updated"] = datetime.now(TW).strftime("%Y-%m-%d %H:%M")
    OUT.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    print("已寫入", OUT)


if __name__ == "__main__":
    main()
