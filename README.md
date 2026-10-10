# Cash Town Fishing Log

A fish guide for Cash Town: which fish bite with which weather, lure, water depth and time of day.

**https://bigcatclaw.github.io/cashtown-fishing/**

> ข้อมูลทั้งหมดบันทึกจากการเล่นของผู้จัดทำเอง อาจไม่ครบถ้วนหรือไม่ถูกต้องทั้งหมด ใช้เป็นแนวทางประกอบการเล่นเท่านั้น
>
> Everything here was logged from my own play sessions, so it may be incomplete or wrong. Treat it as a guide.

## How it works

- `index.html` is both the logging tool and the public page. Opened on the logging PC it logs catches; on the website it is a read-only guide built from `data.json`.
- `start.bat` runs `server.py` (Python 3, no extra packages). It saves every catch to a local SQLite file and, 10 minutes after the last change, uploads a fresh `data.json` here.
