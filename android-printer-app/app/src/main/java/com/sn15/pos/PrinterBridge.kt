package com.sn15.pos

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.webkit.JavascriptInterface
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStream
import java.util.UUID
import java.util.concurrent.Executors

/**
 * JavaScript bridge the web POS calls as `window.SnsPrinter`.
 *
 * Talks to a Bluetooth *Classic* (SPP) ESC/POS thermal printer (the Niyama
 * BT-58). The printer must first be PAIRED in Android Settings > Bluetooth
 * (PIN usually 0000 or 1234). After the manager picks it once, its MAC is saved
 * and we auto-connect on every launch and before each print.
 */
class PrinterBridge(private val context: Context, private val ui: (Runnable) -> Unit) {

    // Standard Serial Port Profile UUID — what these ESC/POS printers expose.
    private val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    private val prefs = context.getSharedPreferences("sns_printer", Context.MODE_PRIVATE)
    private val io = Executors.newSingleThreadExecutor()

    @Volatile private var socket: BluetoothSocket? = null
    @Volatile private var output: OutputStream? = null

    private fun savedMac(): String? = prefs.getString("mac", null)
    private fun savedName(): String? = prefs.getString("name", null)

    private fun adapter(): BluetoothAdapter? = BluetoothAdapter.getDefaultAdapter()

    private fun isConnected(): Boolean = socket?.isConnected == true && output != null

    /** Connect to the saved printer (or [mac]). Must run off the UI thread. */
    @Synchronized
    private fun connect(mac: String?): Boolean {
        val target = mac ?: savedMac() ?: return false
        if (isConnected() && socket?.remoteDevice?.address == target) return true
        closeQuietly()
        val a = adapter() ?: return false
        if (!a.isEnabled) return false
        return try {
            val device: BluetoothDevice = a.getRemoteDevice(target)
            a.cancelDiscovery()
            val s = device.createRfcommSocketToServiceRecord(SPP_UUID)
            s.connect()                 // blocks until connected or throws
            socket = s
            output = s.outputStream
            true
        } catch (e: Exception) {
            closeQuietly()
            false
        }
    }

    private fun closeQuietly() {
        try { output?.close() } catch (_: Exception) {}
        try { socket?.close() } catch (_: Exception) {}
        output = null
        socket = null
    }

    /** Called by MainActivity on launch/resume to warm up the connection. */
    fun autoConnect() {
        if (savedMac() == null) return
        io.execute { connect(null) }
    }

    // ---- JavaScript-facing API (window.SnsPrinter.*) ----

    @JavascriptInterface
    fun status(): String {
        val o = JSONObject()
        o.put("connected", isConnected())
        o.put("name", savedName() ?: "")
        o.put("mac", savedMac() ?: "")
        return o.toString()
    }

    /** JSON array of bonded (paired) devices for the picker. */
    @JavascriptInterface
    fun listPaired(): String {
        val arr = JSONArray()
        try {
            adapter()?.bondedDevices?.forEach { d ->
                val o = JSONObject()
                o.put("name", d.name ?: d.address)
                o.put("mac", d.address)
                arr.put(o)
            }
        } catch (_: Exception) {}
        return arr.toString()
    }

    /** Save the chosen printer and connect. Returns "ok" or "error:...". */
    @JavascriptInterface
    fun selectPrinter(mac: String, name: String?): String {
        // Save immediately and connect on a background thread. The Bluetooth
        // connect can block for several seconds, so doing it inline would freeze
        // the UI ("app not responding"). The next print reconnects if needed.
        prefs.edit().putString("mac", mac).putString("name", name ?: mac).apply()
        io.execute { connect(mac) }
        return "ok"
    }

    /** Show a native printer picker (used by the web "Printer Settings" button). */
    @JavascriptInterface
    fun openSettings() {
        ui(Runnable {
            (context as? MainActivity)?.showPrinterPicker()
        })
    }

    /**
     * Print plain text as ESC/POS. Reconnects automatically if needed.
     * Returns "ok" or "error:...". The actual write happens on a worker thread;
     * "ok" means the job was accepted and a printer is connected.
     */
    @JavascriptInterface
    fun print(text: String): String {
        if (savedMac() == null) return "error:no printer selected"
        // ensure connection (may block briefly) — do it synchronously so the
        // return value reflects reality, but on the IO executor via a latch.
        var ok = false
        val task = io.submit {
            if (!isConnected()) connect(null)
            if (isConnected()) {
                try {
                    val out = output!!
                    out.write(byteArrayOf(0x1B, 0x40))          // ESC @  initialise
                    out.write(text.toByteArray(Charsets.ISO_8859_1))
                    out.write("\n\n\n".toByteArray())            // feed past the tear bar
                    out.flush()
                    ok = true
                } catch (e: Exception) {
                    closeQuietly()
                    ok = false
                }
            }
        }
        try { task.get() } catch (_: Exception) {}
        return if (ok) "ok" else "error:printer not reachable (check power & pairing)"
    }
}
