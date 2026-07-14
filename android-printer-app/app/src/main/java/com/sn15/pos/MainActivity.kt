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
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONTokener
import java.io.File

/**
 * Thin native shell: loads the live POS in a full-screen WebView and injects the
 * Bluetooth printer bridge so the web app can print to the BT-58.
 *
 * Offline resilience: unlike a browser-based PWA (whose cache lives in Chrome's
 * storage and is bound by a service worker's lifecycle), this app owns its
 * WebView outright, so it keeps its own on-disk snapshot of the screens that
 * matter for continuing to take orders during an outage (Dashboard, the order
 * screen, and the order list). Whenever one of those loads successfully, its
 * HTML is saved to this app's private storage; if a later load fails — either
 * a flat-out connection failure (no signal at all) or an HTTP error (the
 * device is online but the origin/tunnel behind Cloudflare is down, which
 * surfaces as a 5xx from Cloudflare's edge rather than a connection error) —
 * the last saved snapshot for that exact route is shown instead of a blank
 * error page. Nothing is snapshotted before its first successful load; there
 * is no way to show data this device has never actually been given.
 */
class MainActivity : AppCompatActivity() {

    private val START_URL = "https://test-pos.snfifteen.com/"

    // Routes worth keeping a snapshot of for offline continuity. Keyed by
    // path only (query strings like /orders/new?location=...&placed=...
    // change on every visit and would never match on lookup otherwise).
    private val OFFLINE_SNAPSHOT_PATHS = setOf("/", "/orders/", "/orders/new")

    private lateinit var webView: WebView
    private lateinit var bridge: PrinterBridge

    private fun snapshotFile(path: String): File {
        val safeName = path.replace(Regex("[^a-zA-Z0-9]"), "_").ifEmpty { "root" }
        return File(filesDir, "offline_snapshot$safeName.html")
    }

    private fun pathOf(urlString: String): String? = try {
        Uri.parse(urlString).path
    } catch (e: Exception) {
        null
    }

    private fun saveSnapshot(urlString: String, html: String) {
        val path = pathOf(urlString) ?: return
        if (path !in OFFLINE_SNAPSHOT_PATHS) return
        try {
            snapshotFile(path).writeText(html)
        } catch (e: Exception) {
            // Best-effort — a failed save just means the next outage falls
            // back to whatever was last saved successfully, if anything.
        }
    }

    private fun loadSnapshot(urlString: String): String? {
        val path = pathOf(urlString) ?: return null
        if (path !in OFFLINE_SNAPSHOT_PATHS) return null
        val f = snapshotFile(path)
        return if (f.exists()) try { f.readText() } catch (e: Exception) { null } else null
    }

    /** Serve the saved snapshot for this request's URL, if there is one. */
    private fun tryOfflineFallback(view: WebView?, requestUrl: String) {
        val snapshot = loadSnapshot(requestUrl) ?: return
        view?.loadDataWithBaseURL(requestUrl, snapshot, "text/html", "UTF-8", requestUrl)
    }

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
        webView.webViewClient = object : WebViewClient() {
            // Keep navigation inside the app (same as the default WebViewClient).

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                val path = url?.let { pathOf(it) } ?: return
                if (path !in OFFLINE_SNAPSHOT_PATHS) return
                // evaluateJavascript returns the value JSON-encoded (a quoted,
                // escaped string) — JSONTokener reverses that back to the raw
                // HTML before it's saved.
                view?.evaluateJavascript("document.documentElement.outerHTML") { encoded ->
                    try {
                        val html = JSONTokener(encoded).nextValue() as? String
                        if (html != null) saveSnapshot(url, html)
                    } catch (e: Exception) { /* best-effort */ }
                }
            }

            // No signal at all (airplane mode, no wifi/data) — a connection-
            // level failure on the main page request.
            override fun onReceivedError(
                view: WebView?, request: WebResourceRequest?, error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) {
                    tryOfflineFallback(view, request.url.toString())
                }
            }

            // Device IS online and reaches Cloudflare's edge fine, but the
            // origin/tunnel behind it is down — that surfaces as a 5xx HTTP
            // response from Cloudflare, not a connection error, so it needs
            // its own check (a power cut takes down the origin server and
            // cloudflared together, which is exactly this case).
            override fun onReceivedHttpError(
                view: WebView?, request: WebResourceRequest?, errorResponse: WebResourceResponse?
            ) {
                super.onReceivedHttpError(view, request, errorResponse)
                val code = errorResponse?.statusCode ?: 0
                if (request?.isForMainFrame == true && code >= 500) {
                    tryOfflineFallback(view, request.url.toString())
                }
            }
        }
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
