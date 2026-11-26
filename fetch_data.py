#!/usr/bin/env python3
"""抓取市場資料並寫入 data.json。

用法:  pip install requests && python fetch_data.py
建議每天收盤後（晚上 9:30 之後，融資資料才會更新）執行一次。
"""
import io
import json
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

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
    g = {k: [0.0, 0.0, 0.0] for k in ("foreign", "trust", "dealer", "total")}  # 買進, 賣出, 買賣超
    for row in j["data"]:
        name = row[0]
        vals = [num(row[1]), num(row[2]), num(row[3])]
        if None in vals:
            continue
        if "合計" in name:
            key = "total"
        elif "外資" in name:
            key = "foreign"
        elif "投信" in name:
            key = "trust"
        elif "自營商" in name:
            key = "dealer"
        else:
            continue
        for i, v in enumerate(vals):
            g[key][i] += v
    if not any(g["total"]):  # 沒有合計列時自行加總
        g["total"] = [sum(g[k][i] for k in ("foreign", "trust", "dealer")) for i in range(3)]
    to_yi = lambda v: round(v / 1e8, 2)  # 元 -> 億元
    out = {}
    for k, (b, sl, d) in g.items():
        out[k] = to_yi(d)            # 買賣超（沿用舊欄位名稱）
        out[k + "_buy"] = to_yi(b)   # 買進金額
        out[k + "_sell"] = to_yi(sl) # 賣出金額
    return out


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


# ---------- 期交所：臺指選擇權波動率指數 VIXTWN ----------
VIX_PAGE = "https://www.taifex.com.tw/cht/7/vixDaily3MNew"
# 檔案格式：日期  時間  收盤指數  收盤前1分鐘平均
VIX_LINE = re.compile(r"^\s*(\d{8})\s+\d+\s+([\d.]+)\s+([\d.]+)")


def decode_text(raw):
    if raw[:2] == b"PK":  # zip 檔
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = b"\n".join(z.read(n) for n in z.namelist())
    for enc in ("utf-8-sig", "big5", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def fetch_vixtwn():
    """從期交所頁面找出下載連結，下載檔案並解析每日收盤指數。"""
    html = requests.get(VIX_PAGE, headers=UA, timeout=30).text
    found = re.findall(r"""["'(]([^"'()\s]*(?:/file/|download|\.txt|\.csv|\.zip)[^"'()\s]*)""", html, re.I)
    links = []
    for l in found:
        if re.search(r"\.(css|js|png|jpg|gif|ico|pdf|ods)(\?|$)", l, re.I):
            continue
        u = urljoin(VIX_PAGE, l)
        if u not in links:
            links.append(u)
    print(f"     VIXTWN 找到 {len(links)} 個候選連結")
    out = {}
    for u in links[:20]:
        try:
            r = requests.get(u, headers=UA, timeout=30)
            if r.status_code != 200 or b"<html" in r.content[:500].lower():
                continue
            for line in decode_text(r.content).splitlines():
                m = VIX_LINE.match(line)
                if m:
                    d = m.group(1)
                    out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = float(m.group(2))
            time.sleep(0.5)
        except Exception as e:
            print(f"     略過 {u}: {e}")
    if not out:
        print("     連結清單（供除錯）:", links[:10])
    return out


def main():
    data = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    data.setdefault("institutional", {})
    data.setdefault("margin", {})
    data.setdefault("vixtwn", {})

    # 全球資料：每次整段覆蓋
    for key, sym in [("wti", "CL=F"), ("brent", "BZ=F"), ("usdtwd", "TWD=X"), ("vix", "^VIX")]:
        try:
            data[key] = yahoo(sym)
            print(f"OK   {key}: {len(data[key])} 筆")
        except Exception as e:
            print(f"FAIL {key}: {e}")

    # 台指 VIX：每次合併進既有資料
    try:
        v = fetch_vixtwn()
        data["vixtwn"].update(v)
        print(f"{'OK  ' if v else 'FAIL'} vixtwn: 本次取得 {len(v)} 筆，累計 {len(data['vixtwn'])} 筆")
    except Exception as e:
        print(f"FAIL vixtwn: {e}")

    # 台股資料：只補缺的日期
    today = datetime.now(TW).date()
    for i in range(DAYS, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        day, iso = d.strftime("%Y%m%d"), d.isoformat()
        try:
            if "total_buy" not in data["institutional"].get(iso, {}):  # 缺買進/賣出金額的舊資料會一併回補
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
