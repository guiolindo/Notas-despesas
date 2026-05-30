// Scanner QR para Contas a Pagar — bipador (input text) + camera (jsQR).
// Carregado em /contas-a-pagar/scanner via tag <script> externa para
// respeitar CSP (script-src sem unsafe-inline).

(function () {
  var fb = document.getElementById('cap-scan-feedback');
  function setFeedback(msg, ok) {
    if (!fb) return;
    fb.textContent = msg;
    fb.style.color = ok ? 'var(--success-color, #16a34a)' : 'var(--danger-color, #dc2626)';
  }

  function extractInvoiceId(raw) {
    if (!raw) return null;
    raw = raw.trim();
    var m = raw.match(/\/verify\/([a-f0-9-]{8,})/i);
    if (m) return m[1];
    if (/^[a-f0-9-]{8,}$/i.test(raw)) return raw;
    try {
      var u = new URL(raw);
      var p = u.pathname.match(/\/verify\/([a-f0-9-]{8,})/i);
      if (p) return p[1];
    } catch (e) {}
    return null;
  }

  function goToInvoice(id) {
    setFeedback('Abrindo nota...', true);
    window.location.href = '/invoices/' + encodeURIComponent(id);
  }

  // Bipador / input manual
  var input = document.getElementById('cap-scan-input');
  if (input) {
    function handleSubmit() {
      var id = extractInvoiceId(input.value);
      if (!id) {
        setFeedback('Codigo invalido — nao parece um QR de nota.', false);
        return;
      }
      goToInvoice(id);
    }
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSubmit();
      }
    });
    var _t;
    input.addEventListener('input', function () {
      clearTimeout(_t);
      _t = setTimeout(function () {
        if (extractInvoiceId(input.value)) handleSubmit();
      }, 350);
    });
  }

  // Camera + jsQR
  var stream = null;
  var rafId = null;
  var video = document.getElementById('cap-cam-video');
  var canvas = document.getElementById('cap-cam-canvas');
  var ctx = canvas ? canvas.getContext('2d', { willReadFrequently: true }) : null;
  var status = document.getElementById('cap-cam-status');

  function tick() {
    if (video && video.readyState === video.HAVE_ENOUGH_DATA && ctx) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      try {
        var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
        var code = window.jsQR
          ? jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' })
          : null;
        if (code && code.data) {
          var id = extractInvoiceId(code.data);
          if (id) {
            stopCamera();
            goToInvoice(id);
            return;
          }
          if (status) status.textContent = 'QR lido mas nao parece uma nota: ' + code.data.substring(0, 60);
        }
      } catch (e) {}
    }
    rafId = requestAnimationFrame(tick);
  }

  function stopCamera() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    if (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }
    var wrap = document.getElementById('cap-cam-wrap');
    if (wrap) wrap.classList.add('hidden');
    document.getElementById('cap-cam-start')?.classList.remove('hidden');
    document.getElementById('cap-cam-stop')?.classList.add('hidden');
  }

  var startBtn = document.getElementById('cap-cam-start');
  if (startBtn) {
    startBtn.addEventListener('click', async function () {
      if (!window.jsQR) {
        setFeedback('Biblioteca de QR nao carregou. Verifique a conexao.', false);
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setFeedback('Camera nao disponivel neste navegador.', false);
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment' },
          audio: false,
        });
        video.srcObject = stream;
        video.setAttribute('playsinline', 'true');
        await video.play();
        document.getElementById('cap-cam-wrap').classList.remove('hidden');
        this.classList.add('hidden');
        document.getElementById('cap-cam-stop').classList.remove('hidden');
        if (status) status.textContent = 'Aponte o QR code para a camera.';
        rafId = requestAnimationFrame(tick);
      } catch (e) {
        setFeedback('Falha ao acessar camera: ' + (e.message || e), false);
      }
    });
  }
  document.getElementById('cap-cam-stop')?.addEventListener('click', stopCamera);
  window.addEventListener('beforeunload', stopCamera);
})();
