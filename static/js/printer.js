/*
 * Sip & Snack — receipt printing layer (printer-agnostic).
 *
 * The POS runs inside a native Android wrapper that owns the Bluetooth printer
 * (the Niyama BT-58 is Bluetooth Classic/SPP, which a browser cannot reach).
 * The wrapper injects a `window.SnsPrinter` bridge:
 *
 *     window.SnsPrinter.print(text)      -> prints ESC/POS for `text`, returns "ok" or "error:..."
 *     window.SnsPrinter.status()         -> JSON string: {connected, name, mac}
 *     window.SnsPrinter.openSettings()   -> opens the native printer picker / pairing screen
 *
 * When the bridge is absent (e.g. admin on a desktop browser) we fall back to
 * the browser's print dialog so receipts can still be printed.
 */
(function () {
  const W = 32; // 58mm thermal = 32 chars per line at default font

  function pad(s) { return String(s == null ? '' : s); }
  function center(s) {
    s = pad(s);
    const left = Math.max(0, Math.floor((W - s.length) / 2));
    return ' '.repeat(left) + s;
  }
  function lr(left, right) {
    left = pad(left); right = pad(right);
    const space = Math.max(1, W - left.length - right.length);
    return left + ' '.repeat(space) + right;
  }
  function rule(ch) { return (ch || '-').repeat(W); }

  const SnsReceipt = {
    /**
     * order = {
     *   store, orderNumber, datetime, customer, phone, orderType,
     *   items: [{ name, qty, price }],
     *   total
     * }
     */
    build(order) {
      const o = order || {};
      const items = o.items || [];
      let t = '';
      t += center(o.store || 'Sip & Snack') + '\n';
      t += center('RECEIPT') + '\n';
      t += rule('=') + '\n';
      if (o.orderNumber) t += 'Order : ' + o.orderNumber + '\n';
      if (o.datetime)    t += 'Date  : ' + o.datetime + '\n';
      if (o.orderType)   t += 'Type  : ' + o.orderType + '\n';
      if (o.customer)    t += 'Cust  : ' + o.customer + '\n';
      if (o.phone)       t += 'Phone : ' + o.phone + '\n';
      t += rule('-') + '\n';
      t += lr('Item', 'Amount') + '\n';
      t += rule('-') + '\n';
      let total = 0;
      items.forEach(function (it) {
        const qty = Number(it.qty) || 0;
        const price = Number(it.price) || 0;
        const lineAmt = qty * price;
        total += lineAmt;
        t += pad(it.name) + '\n';
        t += lr('  ' + qty + ' x ' + price.toFixed(2), lineAmt.toFixed(2)) + '\n';
      });
      t += rule('-') + '\n';
      const grand = (o.total != null) ? Number(o.total) : total;
      t += lr('TOTAL', 'Rs ' + grand.toFixed(2)) + '\n';
      t += rule('=') + '\n';
      t += center('Thank you! Visit again') + '\n';
      t += '\n\n\n'; // feed so the tear-off clears the print head
      return t;
    }
  };

  const SnsPrinterUI = {
    bridge() {
      return (window.SnsPrinter && typeof window.SnsPrinter.print === 'function')
        ? window.SnsPrinter : null;
    },

    isNative() { return !!this.bridge(); },

    /** Print an already-built receipt string. Returns true if sent to a printer. */
    printText(text) {
      const b = this.bridge();
      if (b) {
        try {
          const res = b.print(text);
          if (res && String(res).indexOf('error') === 0) {
            this._toast('Printer error: ' + res.slice(6) + '. Check it is on & paired.', true);
            return false;
          }
          this._toast('Printing receipt…');
          return true;
        } catch (e) {
          this._toast('Could not reach the printer. Open Printer Settings.', true);
          return false;
        }
      }
      // Desktop / no bridge: use the browser print dialog.
      this._browserPrint(text);
      return false;
    },

    /** Convenience: build from an order object and print. */
    printOrder(order) { return this.printText(SnsReceipt.build(order)); },

    openSettings() {
      const b = this.bridge();
      if (b && typeof b.openSettings === 'function') { b.openSettings(); return; }
      this._toast('Printer setup is available in the installed app.', true);
    },

    _browserPrint(text) {
      const w = window.open('', '_blank', 'width=320,height=640');
      if (!w) { alert(text); return; }
      const safe = text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
      w.document.write('<html><head><title>Receipt</title></head><body>' +
        '<pre style="font:13px/1.35 monospace; white-space:pre-wrap; width:280px;">' + safe + '</pre>' +
        '<script>window.onload=function(){window.print();}<\/script></body></html>');
      w.document.close();
    },

    _toast(msg, isError) {
      let el = document.getElementById('sns-print-toast');
      if (!el) {
        el = document.createElement('div');
        el.id = 'sns-print-toast';
        el.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:90px;z-index:2000;' +
          'padding:.6rem 1rem;border-radius:10px;color:#fff;font:500 14px Roboto,sans-serif;' +
          'box-shadow:0 4px 14px rgba(0,0,0,.25);max-width:90%;text-align:center;';
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
  window.SnsPrint = SnsPrinterUI;
})();
