# 每日市場看板

自動更新：原油、美元兌台幣、三大法人買賣超、融資餘額、VIX。

## 零指令架設（約 5 分鐘）
1. 註冊 / 登入 github.com → 右上角 + → New repository，取名 market-board，選 Public，建立。
2. 點 "uploading an existing file"，把本資料夾內所有檔案（含 .github 資料夾）拖進去 → Commit changes。
3. Settings → Pages → Branch 選 main、資料夾選 / (root) → Save。
4. Actions 分頁 → 左邊「更新市場資料」→ Run workflow（第一次手動跑一次）。
5. 約 2 分鐘後，網址 https://你的帳號.github.io/market-board/ 就是看板，把網址傳給別人即可。

之後每個交易日晚上 22:30（台灣時間）自動更新。
