"""
One-off verification script — NOT part of the application.
Exercises the exact eidli_client.py code path Flask uses (same cwd, same
load_dotenv('.env') resolution) to prove the X-API-Key fix works end-to-end
against the live FastAPI backend, without needing a real browser OAuth
session. Deleted after use.
"""
from dotenv import load_dotenv
load_dotenv('.env')

import os
import eidli_client as eidli

machine_id = os.getenv('EIDLI_MACHINE_ID', '').strip()

print("=== env check ===")
print("EIDLI_API_KEY loaded:", bool(eidli.API_KEY), "| length:", len(eidli.API_KEY))
print("Header that will be sent:", {k: ('***redacted***' if k == 'X-API-Key' else v) for k, v in eidli._headers().items()})
print()

def show(label, fn):
    try:
        result = fn()
        print(f"[OK] {label}")
        print("     ->", result)
    except eidli.EidliError as e:
        print(f"[FAIL] {label}: HTTP {e.status} - {e.message}")
    print()

print("=== GET (read) endpoints — must NOT require the key ===")
show("GET /status", lambda: eidli.get_machine_status(machine_id))
show("GET /settings", lambda: eidli.get_settings(machine_id))

print("=== Protected (mutating) endpoints — safe/idempotent subset only ===")
show("POST /heater/off (heater already OFF - idempotent)", lambda: eidli.heater_off(machine_id))
show("PATCH /settings (buzzer_enabled=True, same as current - no-op)", lambda: eidli.update_settings(machine_id, {"buzzer_enabled": True}))
show("PATCH /settings (thresholds re-sent at current values - no-op)", lambda: eidli.update_settings(machine_id, {"on_temperature": "85.00", "off_temperature": "90.00"}))
show("PATCH /settings (mode: manual -> auto)", lambda: eidli.update_settings(machine_id, {"mode": "auto"}))
show("PATCH /settings (mode: auto -> manual, restoring original)", lambda: eidli.update_settings(machine_id, {"mode": "manual"}))
show("POST /settings/sync", lambda: eidli.sync_settings(machine_id))
