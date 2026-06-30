/*
 * Sip & Snack — receipt printing layer (printer-agnostic).
 *
 * The POS runs inside a native Android wrapper that owns the Bluetooth printer
 * via `window.SnsPrinter` (the BT-58 and almost every cheap thermal printer are
 * Bluetooth Classic / SPP, which a browser cannot reach). Bridge methods:
 *
 *     window.SnsPrinter.print(text)      -> prints ESC/POS for `text`
 *     window.SnsPrinter.status()         -> JSON: {connected, name, mac}
 *     window.SnsPrinter.listPaired()     -> JSON array of paired devices
 *     window.SnsPrinter.selectPrinter()  -> native picker
 *     window.SnsPrinter.openSettings()   -> native picker
 *
 * This file is printer-agnostic: any paired ESC/POS printer works. The only
 * thing that varies between printers is paper width (58mm = 32 chars,
 * 80mm = 48 chars), which is a saved setting here so swapping printers is easy.
 */
(function () {
  function paperChars() {
    var v = parseInt(localStorage.getItem('sns_paper_chars'), 10);
    return v === 48 ? 48 : 32;            // 32 = 58mm (default), 48 = 80mm
  }
  function setPaperChars(n) { localStorage.setItem('sns_paper_chars', String(n === 48 ? 48 : 32)); }

  function pad(s) { return String(s == null ? '' : s); }
  function center(s, W) { s = pad(s); var l = Math.max(0, Math.floor((W - s.length) / 2)); return ' '.repeat(l) + s; }
  function lr(left, right, W) { left = pad(left); right = pad(right); var sp = Math.max(1, W - left.length - right.length); return left + ' '.repeat(sp) + right; }
  function rule(ch, W) { return (ch || '-').repeat(W); }

  var SnsReceipt = {
    /** order = { store, orderNumber, datetime, customer, phone, orderType, items:[{name,qty,price}], total } */
    build: function (order) {
      var o = order || {}, items = o.items || [], W = paperChars();
      var ESC = '\x1B', GS = '\x1D';
      var t = '';
      // Branded header — centered, double-size, bold "Sip & Snack" wordmark.
      // These are standard ESC/POS codes (passed straight through to the
      // printer); the browser-print fallback strips them so it stays readable.
      t += ESC + 'a' + '\x01';                                   // center
      t += GS + '!' + '\x11' + ESC + 'E' + '\x01';               // double w+h, bold on
      t += 'Sip & Snack' + '\n';
      t += GS + '!' + '\x00' + ESC + 'E' + '\x00';               // normal size, bold off
      if (o.store) t += o.store + '\n';
      t += 'RECEIPT' + '\n';
      t += ESC + 'a' + '\x00';                                   // back to left
      t += rule('=', W) + '\n';
      if (o.orderNumber) t += 'Order : ' + o.orderNumber + '\n';
      if (o.datetime)    t += 'Date  : ' + o.datetime + '\n';
      if (o.orderType)   t += 'Type  : ' + o.orderType + '\n';
      if (o.customer)    t += 'Cust  : ' + o.customer + '\n';
      if (o.phone)       t += 'Phone : ' + o.phone + '\n';
      t += rule('-', W) + '\n';
      t += lr('Item', 'Amount', W) + '\n';
      t += rule('-', W) + '\n';
      var total = 0;
      items.forEach(function (it) {
        var qty = Number(it.qty) || 0, price = Number(it.price) || 0, amt = qty * price;
        total += amt;
        t += pad(it.name) + '\n';
        t += lr('  ' + qty + ' x ' + price.toFixed(2), amt.toFixed(2), W) + '\n';
      });
      t += rule('-', W) + '\n';
      var grand = (o.total != null) ? Number(o.total) : total;
      t += lr('TOTAL', 'Rs ' + grand.toFixed(2), W) + '\n';
      t += rule('=', W) + '\n';
      t += center('Thank you! Visit again', W) + '\n';
      t += '\n\n\n';
      return t;
    }
  };

  var SnsPrint = {
    bridge: function () { return (window.SnsPrinter && typeof window.SnsPrinter.print === 'function') ? window.SnsPrinter : null; },
    isNative: function () { return !!this.bridge(); },

    printText: function (text) {
      var b = this.bridge();
      if (b) {
        try {
          var res = b.print(text);
          if (res && String(res).indexOf('error') === 0) {
            this._toast('Printer error: ' + String(res).slice(6) + '. Check it is on & paired.', true);
            return false;
          }
          this._toast('Printing receipt…');
          return true;
        } catch (e) {
          this._toast('Could not reach the printer. Open Printer Settings.', true);
          return false;
        }
      }
      this._browserPrint(text);
      return false;
    },

    printOrder: function (order) { return this.printText(SnsReceipt.build(order)); },

    setPaper: function (mm) { setPaperChars(String(mm) === '80' ? 48 : 32); },

    /** Printer Settings panel: choose printer (native) + paper size. Web-based,
     *  so it works for any future printer with no app rebuild. */
    openSettings: function () {
      var self = this;
      var existing = document.getElementById('sns-printer-panel');
      if (existing) existing.remove();

      var status = { connected: false, name: '' };
      var b = this.bridge();
      if (b && b.status) { try { status = JSON.parse(b.status()); } catch (e) {} }

      var overlay = document.createElement('div');
      overlay.id = 'sns-printer-panel';
      overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:3000;display:flex;align-items:center;justify-content:center;padding:1rem;';
      var cur = paperChars();
      overlay.innerHTML =
        '<div style="background:#fff;border-radius:14px;max-width:380px;width:100%;padding:1.25rem;font-family:Roboto,sans-serif;">' +
          '<h5 style="margin:0 0 .75rem;">🖨️ Printer Settings</h5>' +
          '<div style="font-size:.9rem;color:#374151;margin-bottom:.75rem;">' +
            'Current printer: <b>' + (status.name ? status.name : 'none selected') + '</b>' +
            (status.connected ? ' <span style="color:#15803d;">(connected)</span>' : '') +
          '</div>' +
          (this.isNative()
            ? '<button id="sns-pick" style="width:100%;padding:.7rem;border:none;border-radius:10px;background:#0d6efd;color:#fff;font-weight:600;margin-bottom:1rem;">Choose / change Bluetooth printer</button>'
            : '<div style="background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:.6rem;font-size:.85rem;margin-bottom:1rem;">Open the installed app to connect a Bluetooth printer.</div>') +
          '<div style="font-size:.9rem;font-weight:600;margin-bottom:.4rem;">Paper size</div>' +
          '<label style="display:block;margin-bottom:.35rem;"><input type="radio" name="sns-paper" value="32" ' + (cur === 32 ? 'checked' : '') + '> 58 mm (small / BT-58)</label>' +
          '<label style="display:block;margin-bottom:1rem;"><input type="radio" name="sns-paper" value="48" ' + (cur === 48 ? 'checked' : '') + '> 80 mm (wide)</label>' +
          '<button id="sns-done" style="width:100%;padding:.7rem;border:1px solid #d1d5db;border-radius:10px;background:#f9fafb;font-weight:600;">Done</button>' +
        '</div>';
      document.body.appendChild(overlay);

      overlay.addEventListener('change', function (e) {
        if (e.target && e.target.name === 'sns-paper') setPaperChars(parseInt(e.target.value, 10));
      });
      var pick = overlay.querySelector('#sns-pick');
      if (pick) pick.addEventListener('click', function () {
        var bb = self.bridge();
        if (bb && bb.openSettings) bb.openSettings();
        else if (bb && bb.selectPrinter) bb.selectPrinter();
      });
      overlay.querySelector('#sns-done').addEventListener('click', function () { overlay.remove(); });
      overlay.addEventListener('click', function (e) { if (e.target === overlay) overlay.remove(); });
    },

    _browserPrint: function (text) {
      var w = window.open('', '_blank', 'width=320,height=640');
      if (!w) { alert(text); return; }
      // Strip ESC/POS control codes (keep newlines) so the on-screen fallback is clean.
      var safe = String(text).replace(/[\x00-\x09\x0B-\x1F]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
      w.document.write('<html><head><title>Receipt</title></head><body>' +
        '<pre style="font:13px/1.35 monospace; white-space:pre-wrap; width:280px;">' + safe + '</pre>' +
        '<script>window.onload=function(){window.print();}<\/script></body></html>');
      w.document.close();
    },

    _toast: function (msg, isError) {
      var el = document.getElementById('sns-print-toast');
      if (!el) {
        el = document.createElement('div');
        el.id = 'sns-print-toast';
        el.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:90px;z-index:2000;padding:.6rem 1rem;border-radius:10px;color:#fff;font:500 14px Roboto,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.25);max-width:90%;text-align:center;';
        document.body.appendChild(el);
      }
      el.style.background = isError ? '#b00020' : '#0d6efd';
      el.textContent = msg;
      el.style.display = 'block';
      clearTimeout(el._t);
      el._t = setTimeout(function () { el.style.display = 'none'; }, isError ? 4000 : 2000);
    }
  };

  window.SnsReceipt = SnsReceipt;
  window.SnsPrint = SnsPrint;
})();
