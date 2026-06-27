# Sip & Snack — native Android app with Bluetooth printing

This replaces the PWABuilder TWA. It loads the **same live site**
(`https://pos.snfifteen.com`) in a full‑screen WebView, but adds a native
**Bluetooth bridge** so the POS can print receipts to the **Niyama BT‑58**
(a Bluetooth *Classic* / SPP thermal printer that a plain web app cannot reach).

It remembers the printer and **auto‑connects on every launch** and before each
print, so managers don't re‑pair each time.

---

## How it fits together
- Web POS calls `window.SnsPrinter.print(text)` (see `static/js/printer.js` in the
  main repo). On desktop (no bridge) it falls back to the browser print dialog.
- The native `PrinterBridge` connects to the saved printer over Bluetooth SPP and
  writes ESC/POS bytes. The printer's MAC is saved in `SharedPreferences`.
- "Printer Settings" in the web app calls `SnsPrinter.openSettings()`, which shows
  a native list of *paired* printers to choose from.

## Build it (one time, on your PC — needs Android Studio)

The most reliable path is to let Android Studio generate the scaffolding and then
drop in the two Kotlin files:

1. **Android Studio → New Project → "Empty Views Activity"** (NOT Compose).
   - Name: `Sip & Snack`  ·  Package name: **`com.sn15.pos`**  ·  Language: **Kotlin**
   - Minimum SDK: **API 24**.
2. Replace `app/src/main/java/com/sn15/pos/MainActivity.kt` with the one here, and
   add `PrinterBridge.kt` next to it (both in package `com.sn15.pos`).
3. Open `app/src/main/AndroidManifest.xml` and add the **Bluetooth + Internet
   permissions** from the manifest here (the `<uses-permission .../>` lines), and
   make sure the `MainActivity` is the launcher activity.
4. Confirm `START_URL` in `MainActivity.kt` is `https://pos.snfifteen.com/`.
5. **Build → Build Bundle(s)/APK(s) → Build APK(s)** → install the APK on the phone
   (`app-debug.apk` is fine for sideloading).

> The `build.gradle`, `settings.gradle`, etc. in this folder are a working
> reference (AGP 8.5, Kotlin 1.9, compileSdk 34). If you build from scratch with
> them, also add a Gradle wrapper and a launcher icon — which is why the
> "New Project + drop‑in files" route above is easier.

## First‑time setup on each phone
1. **Pair the printer once in Android Settings → Bluetooth.** Turn the BT‑58 on,
   pair it (PIN is usually **0000** or **1234**). This OS‑level bonding is required
   for SPP.
2. Open the **Sip & Snack** app → log in → place/open an order → **Printer Settings**
   → pick the BT‑58. It's saved.
3. From now on it auto‑connects. Tapping **Print Receipt** (or placing an order,
   which auto‑prints) sends the receipt to the printer.

## Google sign-in inside the WebView
Google blocks "Sign in with Google" from Android WebViews that advertise the
`; wv` user-agent (`disallowed_useragent`). `MainActivity` already strips that
marker so the UA looks like normal Chrome and login works. If Google ever
tightens this and the strip stops working, the fallback is to open the OAuth
flow in a **Chrome Custom Tab** and return via a deep link — ask and I'll wire it.

## Notes / troubleshooting
- If a print fails with "printer not reachable", the printer is off or out of
  range — turn it on and try again; the app reconnects automatically.
- The BT‑58 has no auto‑cutter; receipts feed a few lines so you can tear them.
- 58 mm paper = 32 characters per line (already handled in `printer.js`).
- Updating the **website** never needs a new APK — only changing the app name,
  icon, package id, or start URL does.
- Keep the signing key safe if you switch from the debug key to a release key
  (needed to ship app updates with the same identity).
