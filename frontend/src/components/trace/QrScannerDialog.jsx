import { useEffect, useRef, useState } from 'react';
import jsQR from 'jsqr';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';

/**
 * A live camera QR scanner in a dialog.
 *
 * It does one job: turn a camera into a string. What the string means is the
 * caller's business (`parseHoneyChainQr` and the existing verification flow).
 *
 * ## The camera is a resource with an owner
 *
 * The stream is opened by `CameraScanner` and closed by the same component, and
 * `stop()` is the only place that releases it: every `MediaStreamTrack` is
 * stopped and the `<video>` is detached. It runs when a code is detected
 * (*before* the caller is told, so the camera is already off when the dialog
 * starts closing), when the dialog is cancelled or closed, and when the
 * component unmounts — and it is idempotent, so running twice is harmless. A
 * stream that arrives after the scanner has already gone (the permission prompt
 * was answered late) is stopped the moment it lands.
 *
 * ## Decoding
 *
 * Frames are drawn to a canvas at reduced size a few times a second and decoded
 * with jsQR. That works in every browser with `getUserMedia`, unlike the native
 * `BarcodeDetector`, which Firefox and desktop Safari do not ship.
 *
 * Camera access needs a secure context (HTTPS, or localhost); on a plain-`http`
 * origin that is neither, the browser hides `navigator.mediaDevices` and this
 * reports `insecure-context` — separately from `unsupported`, because the first
 * one the person can fix by opening the app at its https address.
 */

/** How the camera can fail to start — the caller words each for a person. */
export const CAMERA_ERRORS = {
  DENIED: 'denied',
  NO_CAMERA: 'no-camera',
  IN_USE: 'in-use',
  /**
   * The page is not a secure context, so the browser has hidden the camera API
   * altogether. This is a *fixable* address problem, not a browser that lacks
   * the feature, and it is the one failure a person can usually do something
   * about — so it is reported apart from {@link CAMERA_ERRORS.UNSUPPORTED}.
   */
  INSECURE_CONTEXT: 'insecure-context',
  UNSUPPORTED: 'unsupported',
};

/**
 * True when the browser is withholding the camera because the page is on a
 * plain `http://` address that is not a trusted origin.
 *
 * Camera access is a secure-context feature: on `https://`, on `localhost`, and
 * on the loopback address it is available, while on `http://192.168.…` the
 * browser removes `navigator.mediaDevices` entirely — which looks identical to
 * "this browser cannot scan" unless the reason is asked for.
 */
function isInsecureContext() {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext === false &&
    window.location?.protocol !== 'https:'
  );
}

export function classifyCameraError(error) {
  switch (error?.name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return CAMERA_ERRORS.DENIED;
    // A `SecurityError` is raised both by a refused permission and by an
    // insecure origin; which one it is decides what the person should do.
    case 'SecurityError':
      return isInsecureContext() ? CAMERA_ERRORS.INSECURE_CONTEXT : CAMERA_ERRORS.DENIED;
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return CAMERA_ERRORS.NO_CAMERA;
    default:
      return CAMERA_ERRORS.IN_USE;
  }
}

const SCAN_INTERVAL_MS = 120; // ~8 decodes a second is plenty for a held-still label
const MAX_FRAME_WIDTH = 720; // decode on a downscaled frame: faster, and QR modules stay large

function CameraScanner({ onDetected, onError, stopRef }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [status, setStatus] = useState('starting');

  // Latest callbacks, read at call time, so the camera effect below runs once.
  const onDetectedRef = useRef(onDetected);
  const onErrorRef = useRef(onError);
  onDetectedRef.current = onDetected;
  onErrorRef.current = onError;

  useEffect(() => {
    const video = videoRef.current;
    let stream = null;
    let timer = 0;
    let finished = false;

    // The one place the camera is released. Idempotent.
    const stop = () => {
      finished = true;
      window.clearTimeout(timer);
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
      }
      if (video) {
        try {
          video.pause();
        } catch {
          /* a detached element has nothing to pause */
        }
        video.srcObject = null;
      }
    };

    const scan = () => {
      if (finished) return;
      const canvas = canvasRef.current;
      if (video && canvas && video.readyState >= 2 && video.videoWidth > 0) {
        const scale = Math.min(1, MAX_FRAME_WIDTH / video.videoWidth);
        const width = Math.max(1, Math.round(video.videoWidth * scale));
        const height = Math.max(1, Math.round(video.videoHeight * scale));
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext('2d', { willReadFrequently: true });
        context.drawImage(video, 0, 0, width, height);
        const frame = context.getImageData(0, 0, width, height);
        const found = jsQR(frame.data, width, height, { inversionAttempts: 'attemptBoth' });
        if (found?.data) {
          // Camera off first, then tell the caller.
          stop();
          onDetectedRef.current?.(found.data);
          return;
        }
      }
      timer = window.setTimeout(scan, SCAN_INTERVAL_MS);
    };

    const start = async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        // Two very different causes look the same from the outside: an origin
        // the browser does not trust with a camera, and a browser that has no
        // camera API at all. The first one is worth telling the person about.
        onErrorRef.current?.(
          isInsecureContext() ? CAMERA_ERRORS.INSECURE_CONTEXT : CAMERA_ERRORS.UNSUPPORTED,
        );
        return;
      }
      try {
        const opened = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' } },
          audio: false,
        });
        if (finished) {
          // Closed while the permission prompt was open: release it straight away.
          opened.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = opened;
        video.srcObject = opened;
        await video.play();
        if (finished) return;
        setStatus('scanning');
        scan();
      } catch (caught) {
        if (finished) return;
        stop();
        onErrorRef.current?.(classifyCameraError(caught));
      }
    };

    // Lets the dialog release the camera the instant it is cancelled, without
    // waiting for the modal's exit animation to unmount this component.
    if (stopRef) stopRef.current = stop;

    start();
    return () => {
      stop();
      if (stopRef && stopRef.current === stop) stopRef.current = null;
    };
  }, [stopRef]);

  return (
    <div className="space-y-3">
      <div className="relative mx-auto aspect-square w-full max-w-sm overflow-hidden rounded-lg bg-ink">
        <video
          ref={videoRef}
          className="h-full w-full object-cover"
          playsInline
          muted
          autoPlay
          data-testid="qr-camera-preview"
        />
        {/* Framing guide only — it does not restrict where a code is read. */}
        <div
          className="pointer-events-none absolute inset-[15%] rounded-lg border-2 border-honey-400/90"
          aria-hidden="true"
        />
        <canvas ref={canvasRef} className="hidden" aria-hidden="true" />
      </div>
      <p className="text-center text-sm text-ink-soft" role="status">
        {status === 'starting'
          ? 'Starting the camera… allow camera access if your browser asks.'
          : 'Point the camera at the QR code on the jar.'}
      </p>
    </div>
  );
}

export function QrScannerDialog({ open, onClose, onDetected, onError }) {
  const stopRef = useRef(null);

  // Each opening gets its own scanner instance. The modal animates out for a
  // moment after it closes; reopening inside that window would otherwise reuse
  // the scanner that has already finished and hand back a dead camera.
  const sessionRef = useRef(0);
  const wasOpenRef = useRef(false);
  if (open && !wasOpenRef.current) sessionRef.current += 1;
  wasOpenRef.current = open;

  // Every way of closing (Cancel, the X, Escape, the backdrop) goes through here:
  // the camera is released first, then the parent hides the dialog.
  const close = () => {
    stopRef.current?.();
    onClose?.();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Scan QR Code"
      description="Hold the HoneyChain label in view. It is read on this device and nothing is recorded."
      size="sm"
      footer={
        <Button variant="secondary" onClick={close}>
          Cancel
        </Button>
      }
    >
      {/* Mounted only while open: closing unmounts it, which stops the camera. */}
      {open ? (
        <CameraScanner
          key={sessionRef.current}
          onDetected={onDetected}
          onError={onError}
          stopRef={stopRef}
        />
      ) : null}
    </Modal>
  );
}

export default QrScannerDialog;
