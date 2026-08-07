"""
Entegrasyon Test Scripti — DijitalVarlik agent_core pipeline dogrulamasi.

Kullanim:
    python verify_integration.py

Basarili cikti ornegi:
    [OK] agent_core saglik: alive
    [OK] eliza: True
    [OK] Gorev olusturuldu, task_id: abc123
    [OK] Gorev durumu: finished
    ENTEGRASYON TESTI BASARILI
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

AGENT_CORE_URL = "http://localhost:5060"
COCKPIT_URL = "http://localhost:5050"
TIMEOUT = 30.0


async def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[OK]" if ok else "[FAIL]"
    msg = f"{status} {label}"
    if detail:
        msg += f": {detail}"
    print(msg)
    return ok


async def run_tests() -> bool:
    all_ok = True

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # 1) agent_core saglik
        try:
            r = await client.get(f"{AGENT_CORE_URL}/health")
            data = r.json()
            ok = data.get("status") == "alive"
            all_ok &= await check("agent_core saglik", ok, data.get("status", "?"))
            eliza_ok = data.get("services", {}).get("eliza", False)
            all_ok &= await check("eliza servisi", eliza_ok, str(eliza_ok))
        except Exception as e:
            all_ok = False
            await check("agent_core saglik", False, str(e))

        # 2) Cockpit saglik
        try:
            r = await client.get(f"{COCKPIT_URL}/health")
            data = r.json()
            ok = data.get("status") == "alive"
            all_ok &= await check("Cockpit saglik", ok, data.get("status", "?"))
        except Exception as e:
            # Cockpit opsiyonel — hata sayilmaz
            await check("Cockpit saglik", False, f"(opsiyonel) {e}")

        # 3) Gorev olustur
        try:
            r = await client.post(
                f"{AGENT_CORE_URL}/task",
                json={"intent": "Sistem testi — entegrasyon dogrulama"},
            )
            if r.status_code in (200, 201):
                data = r.json()
                task_id = data.get("task_id") or data.get("id")
                all_ok &= await check("Gorev olusturuldu", bool(task_id), f"task_id: {task_id}")

                # 4) Gorev durumunu sorgula (max 20 sn bekle)
                if task_id:
                    status_url = f"{AGENT_CORE_URL}/task/{task_id}"
                    finished = False
                    for _ in range(10):
                        await asyncio.sleep(2)
                        try:
                            sr = await client.get(status_url)
                            sd = sr.json()
                            st = sd.get("status", "unknown")
                            if st in ("finished", "done", "completed"):
                                finished = True
                                break
                            elif st in ("error", "failed"):
                                break
                        except Exception:
                            break
                    all_ok &= await check("Gorev tamamlandi", finished, st if not finished else "finished")
            else:
                all_ok &= await check("Gorev olusturuldu", False, f"HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            all_ok &= await check("Gorev olusturuldu", False, str(e))

        # 5) Handover endpoint testi (Cockpit)
        try:
            r = await client.post(
                f"{COCKPIT_URL}/api/handover",
                json={
                    "type": "handover_alert",
                    "target": "@test_entegrasyon",
                    "score": 9.0,
                    "achilles_heel": "Entegrasyon test dogrulamasi",
                    "chat_history": [
                        {"sender": "ajan", "message": "Sistem calisiyor"},
                        {"sender": "hedef", "message": "Merhaba"},
                    ],
                },
            )
            ok = r.status_code == 200 and r.json().get("status") == "broadcast"
            all_ok &= await check(
                "Handover Cockpit broadcast",
                ok,
                r.json().get("status", f"HTTP {r.status_code}"),
            )
        except Exception as e:
            await check("Handover Cockpit broadcast", False, f"(Cockpit kapali olabilir) {e}")

    return all_ok


if __name__ == "__main__":
    print("=" * 55)
    print("  DIJITALVARLIK ENTEGRASYON TESTI")
    print("=" * 55)
    ok = asyncio.run(run_tests())
    print("=" * 55)
    if ok:
        print("  ENTEGRASYON TESTI BASARILI")
    else:
        print("  BAZI TESTLER BASARISIZ (detay yukari bak)")
    print("=" * 55)
    sys.exit(0 if ok else 1)
