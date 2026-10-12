# Cash Town Fishing Log

A fish guide for Cash Town: which fish bite with which weather, lure, water depth and time of day.

**https://bigcatclaw.github.io/cashtown-fishing/**

> ข้อมูลทั้งหมดบันทึกจากการเล่นของผู้จัดทำเอง อาจไม่ครบถ้วนหรือไม่ถูกต้องทั้งหมด ใช้เป็นแนวทางประกอบการเล่นเท่านั้น
>
> Everything here was logged from my own play sessions, so it may be incomplete or wrong. Treat it as a guide.

## How it works

- `index.html` is both the logging tool and the public page. Opened on the logging PC it logs catches; on the website it is a read-only guide built from `data.json`.
- `start.bat` runs `server.py` (Python 3, no extra packages). It saves every catch to a local SQLite file and, 10 minutes after the last change, uploads a fresh `data.json` here.

## Logging catches automatically from the game

`cashtown-autolog.user.js` is a Tampermonkey script for the Cash Town page. When the fishing result popup shows what you landed, it sends each fish (with its length and the water depth) to the log on the same PC, which saves it with the conditions currently set there.

1. Install the [Tampermonkey](https://www.tampermonkey.net/) extension. In Chrome, open the extension's details and turn on **Allow User Scripts**.
2. Open **https://bigcatclaw.github.io/cashtown-fishing/cashtown-autolog.user.js** and click **Install**.
3. Run `start.bat` and keep the log page open while you play. Keep the game language on ไทย.
