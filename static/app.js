document.addEventListener('click', function (e) {
  var t = e.target.closest('[data-print]'); if (t) { e.preventDefault(); window.print(); }
});
document.addEventListener('change', function (e) {
  var t = e.target.closest('[data-autosubmit]'); if (t && t.form) t.form.submit();
});

/* Installable app: service worker registration and a dismissible install prompt. */
(function () {
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {}); });
  }
  var standalone = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone;
  if (standalone) return;
  try { if (localStorage.getItem('pwa-dismissed') === '1') return; } catch (e) {}
  var deferred = null, bar = null;
  function show(message, canInstall) {
    if (bar) return;
    bar = document.createElement('div'); bar.className = 'install-bar'; bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', 'Install app');
    var text = document.createElement('span'); text.textContent = message; bar.appendChild(text);
    if (canInstall) {
      var go = document.createElement('button'); go.type = 'button'; go.className = 'install-go'; go.textContent = 'Install';
      go.addEventListener('click', function () { if (!deferred) return; deferred.prompt(); deferred.userChoice.finally(function () { deferred = null; hide(); }); });
      bar.appendChild(go);
    }
    var close = document.createElement('button'); close.type = 'button'; close.className = 'install-close'; close.setAttribute('aria-label', 'Dismiss'); close.textContent = '×';
    close.addEventListener('click', function () { try { localStorage.setItem('pwa-dismissed', '1'); } catch (e) {} hide(); });
    bar.appendChild(close); document.body.appendChild(bar);
  }
  function hide() { if (bar) { bar.remove(); bar = null; } }
  window.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); deferred = e; show('Install this app on your device for quick access.', true); });
  window.addEventListener('appinstalled', hide);
  if (/iphone|ipad|ipod/i.test(navigator.userAgent) && !/crios|fxios/i.test(navigator.userAgent)) {
    document.addEventListener('DOMContentLoaded', function () { show('To install: tap Share, then Add to Home Screen.', false); });
  }
})();

/* ---- Webcam capture for passport photographs -------------------------------
   Adds a "Take photo" button beside every passport photo upload. The captured
   picture is placed in the normal file input, so the server validates and
   stores it exactly like an uploaded file. Needs HTTPS (or localhost). */
(function () {
  function setup(input) {
    if (input.dataset.cameraReady) return;
    input.dataset.cameraReady = '1';
    var box = document.createElement('div');
    box.className = 'cam-box';
    var openBtn = document.createElement('button');
    openBtn.type = 'button'; openBtn.className = 'btn ghost cam-open'; openBtn.textContent = '📷 Take photo with camera';
    var msg = document.createElement('p'); msg.className = 'cam-msg subtle'; msg.setAttribute('role', 'status');
    var panel = document.createElement('div'); panel.className = 'cam-panel'; panel.hidden = true;
    var video = document.createElement('video'); video.autoplay = true; video.muted = true; video.setAttribute('playsinline', '');
    var canvas = document.createElement('canvas'); canvas.hidden = true;
    var bar = document.createElement('div'); bar.className = 'cam-bar';
    function mk(t, c) { var b = document.createElement('button'); b.type = 'button'; b.className = c; b.textContent = t; return b; }
    var snap = mk('Capture', 'btn cam-snap'), retake = mk('Retake', 'btn ghost cam-retake'), close = mk('Cancel', 'btn ghost cam-close');
    retake.hidden = true;
    bar.appendChild(snap); bar.appendChild(retake); bar.appendChild(close);
    panel.appendChild(video); panel.appendChild(canvas); panel.appendChild(bar);
    box.appendChild(openBtn); box.appendChild(msg); box.appendChild(panel);
    input.parentNode.insertBefore(box, input.nextSibling);

    var stream = null;
    function stop() { if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; } video.srcObject = null; }
    function say(t) { msg.textContent = t || ''; }
    function show(live) { video.hidden = !live; canvas.hidden = live; snap.hidden = !live; retake.hidden = live; }

    function start() {
      say('');
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        say(window.isSecureContext ? 'This browser cannot use the camera. Please upload a photo file instead.' : 'The camera only works on a secure (https) connection. Please upload a photo file instead.');
        return;
      }
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false }).then(function (s) {
        stream = s; video.srcObject = s; panel.hidden = false; openBtn.hidden = true; show(true);
        var p = video.play(); if (p && p.catch) p.catch(function () {});
      }).catch(function (e) {
        var n = e && e.name;
        say(n === 'NotAllowedError' || n === 'SecurityError' ? 'Camera permission was blocked. Allow the camera for this site in your browser settings, or upload a photo file.'
          : n === 'NotFoundError' || n === 'OverconstrainedError' ? 'No camera was found on this device. Please upload a photo file instead.'
          : 'The camera could not be started. Please upload a photo file instead.');
      });
    }
    function closePanel() { stop(); panel.hidden = true; openBtn.hidden = false; }

    snap.addEventListener('click', function () {
      var w = video.videoWidth, h = video.videoHeight;
      if (!w || !h) { say('The camera is still starting. Try again in a moment.'); return; }
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(video, 0, 0, w, h);
      canvas.toBlob(function (blob) {
        if (!blob) { say('The photo could not be captured. Please try again.'); return; }
        try {
          var file = new File([blob], 'camera-photo.jpg', { type: 'image/jpeg' });
          var dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
        } catch (err) { say('This browser could not attach the photo. Please upload a photo file instead.'); closePanel(); return; }
        stop(); show(false); say('Photo captured and attached. Save the form to keep it, or Retake.');
      }, 'image/jpeg', 0.92);
    });
    retake.addEventListener('click', function () { input.value = ''; start(); });
    close.addEventListener('click', function () { closePanel(); say(input.files && input.files.length ? 'Photo attached.' : ''); });
    openBtn.addEventListener('click', start);
    window.addEventListener('pagehide', stop);
  }
  function init() { Array.prototype.forEach.call(document.querySelectorAll('input[type=file][name=passport_photo]'), setup); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

/* User form: a new Subject Teacher defaults to all three JHS classes. */
(function () {
  function init() {
    var role = document.querySelector('select[name=role]'), cls = document.querySelector('select[name=assigned_class]');
    if (!role || !cls) return;
    role.addEventListener('change', function () {
      if (role.value === 'Subject Teacher' && !cls.value) {
        for (var i = 0; i < cls.options.length; i++) { if (cls.options[i].value === 'ST:JHS 1,JHS 2,JHS 3') { cls.selectedIndex = i; break; } }
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

/* Report cards: print one pupil's page only. */
(function () {
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-print-card]'); if (!b) return;
    var sheet = b.closest('.report-sheet'); if (!sheet) return;
    e.preventDefault(); sheet.classList.add('print-target'); document.body.classList.add('print-one'); window.print();
  });
  window.addEventListener('afterprint', function () {
    document.body.classList.remove('print-one');
    Array.prototype.forEach.call(document.querySelectorAll('.print-target'), function (x) { x.classList.remove('print-target'); });
  });
})();
