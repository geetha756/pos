package com.sn15.pos

import android.Manifest
import android.app.AlertDialog
import android.bluetooth.BluetoothAdapter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.net.Uri
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.contract.ActivityResultContracts
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

    // Lets the web page's <input type="file"> (e.g. menu-item photo upload) open
    // the Android file/camera picker. A WebView ignores file inputs without this.
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private val fileChooserLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val cb = filePathCallback
            filePathCallback = null
            cb?.onReceiveValue(
                WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            )
        }

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
        // Custom chrome client so "Choose File" on a web form opens the Android
        // file/camera picker and hands the result back to the page.
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView?,
                callback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?
            ): Boolean {
                filePathCallback?.onReceiveValue(null)   // cancel any pending one
                filePathCallback = callback
                return try {
                    val intent = params?.createIntent() ?: throw IllegalStateException("no intent")
                    fileChooserLauncher.launch(intent)
                    true
                } catch (e: Exception) {
                    filePathCallback = null
                    android.widget.Toast.makeText(
                        applicationContext, "Couldn't open the file picker.",
                        android.widget.Toast.LENGTH_SHORT
                    ).show()
                    false
                }
            }
        }

        // A WebView ignores file downloads (e.g. the Sales PDF) unless we handle
        // them. Hand the URL to Android's DownloadManager, passing the login
        // cookie so the authenticated PDF route can be fetched, and save it to
        // the device's Downloads folder with a completion notification.
        webView.setDownloadListener { url, userAgent, contentDisposition, mimetype, _ ->
            try {
                val request = android.app.DownloadManager.Request(android.net.Uri.parse(url))
                android.webkit.CookieManager.getInstance().getCookie(url)?.let {
                    request.addRequestHeader("Cookie", it)
                }
                request.addRequestHeader("User-Agent", userAgent)
                val fileName = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimetype)
                request.setMimeType(mimetype)
                request.setTitle(fileName)
                request.setDescription("Downloading from Sip & Snack")
                request.setNotificationVisibility(
                    android.app.DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
                )
                request.setDestinationInExternalPublicDir(
                    android.os.Environment.DIRECTORY_DOWNLOADS, fileName
                )
                (getSystemService(android.content.Context.DOWNLOAD_SERVICE) as android.app.DownloadManager)
                    .enqueue(request)
                android.widget.Toast.makeText(
                    applicationContext, "Downloading $fileName…", android.widget.Toast.LENGTH_SHORT
                ).show()
            } catch (e: Exception) {
                android.widget.Toast.makeText(
                    applicationContext, "Download failed: ${e.message}", android.widget.Toast.LENGTH_LONG
                ).show()
            }
        }

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
