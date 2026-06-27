package com.sn15.pos

import android.Manifest
import android.app.AlertDialog
import android.bluetooth.BluetoothAdapter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray

/**
 * Thin native shell: loads the live POS in a full-screen WebView and injects the
 * Bluetooth printer bridge so the web app can print to the BT-58.
 */
class MainActivity : AppCompatActivity() {

    private val START_URL = "https://pos.snfifteen.com/"
    private lateinit var webView: WebView
    private lateinit var bridge: PrinterBridge

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        requestBtPermissionsIfNeeded()

        webView = WebView(this)
        setContentView(webView)

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
            // Google blocks "Sign in with Google" from Android WebViews (which
            // advertise a "; wv" user-agent). Strip that marker so the UA looks
            // like normal Chrome and OAuth is allowed.
            userAgentString = userAgentString.replace("; wv", "")
        }
        // Persist cookies (keeps the login session across app restarts).
        android.webkit.CookieManager.getInstance().setAcceptCookie(true)
        android.webkit.CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)
        webView.webViewClient = WebViewClient()       // keep navigation inside the app
        webView.webChromeClient = WebChromeClient()

        bridge = PrinterBridge(this) { runnable -> runOnUiThread(runnable) }
        webView.addJavascriptInterface(bridge, "SnsPrinter")

        webView.loadUrl(START_URL)
    }

    override fun onResume() {
        super.onResume()
        if (::bridge.isInitialized) bridge.autoConnect()   // reconnect when app comes forward
    }

    // Hardware back button navigates the web history.
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    /** Native paired-printer picker, opened from the web "Printer Settings" button. */
    fun showPrinterPicker() {
        val arr = JSONArray(bridge.listPaired())
        if (arr.length() == 0) {
            AlertDialog.Builder(this)
                .setTitle("No paired printers")
                .setMessage("First pair the BT-58 in Android Settings > Bluetooth (PIN 0000 or 1234), then try again.")
                .setPositiveButton("OK", null)
                .show()
            return
        }
        val names = Array(arr.length()) { i -> arr.getJSONObject(i).getString("name") }
        AlertDialog.Builder(this)
            .setTitle("Select receipt printer")
            .setItems(names) { _, which ->
                val dev = arr.getJSONObject(which)
                val res = bridge.selectPrinter(dev.getString("mac"), dev.getString("name"))
                val msg = if (res == "ok") "Printer set: ${dev.getString("name")}" else res.removePrefix("error:")
                AlertDialog.Builder(this).setMessage(msg).setPositiveButton("OK", null).show()
            }
            .show()
    }

    private fun requestBtPermissionsIfNeeded() {
        val needed = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT)
                != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.BLUETOOTH_CONNECT)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_SCAN)
                != PackageManager.PERMISSION_GRANTED) needed.add(Manifest.permission.BLUETOOTH_SCAN)
        }
        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), 100)
        }
        // Make sure Bluetooth is on.
        BluetoothAdapter.getDefaultAdapter()?.let { if (!it.isEnabled) it.enable() }
    }
}
