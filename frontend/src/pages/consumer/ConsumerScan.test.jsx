import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ConsumerVerificationPage from '@/pages/consumer/ConsumerVerificationPage';

/**
 * The consumer's "Scan QR Code" flow.
 *
 * jsdom has no camera, so `getUserMedia`, `<video>` playback, `<canvas>` and the
 * decoder are stood in for. Everything the feature owns is real: the scanner
 * dialog, its stream handling, the payload parser and the page wiring into the
 * existing verification flow. The QR text used is the exact shape the backend
 * encodes (`<PUBLIC_TRACE_BASE_URL>/<package_code>`).
 */

const { decode } = vi.hoisted(() => ({ decode: vi.fn() }));
vi.mock('jsqr', () => ({ default: (...args) => decode(...args) }));

// The report and the header are existing components with their own concerns; a
// stub that shows which code the report was asked for is enough to prove the
// scan reached the existing verification flow.
vi.mock('@/components/trace/TraceReport', () => ({
  TraceReport: ({ code }) => <div data-testid="trace-report">{code}</div>,
}));
vi.mock('@/components/common/WorkspaceHeader', () => ({ WorkspaceHeader: () => null }));

const LABEL_A = 'http://localhost:4173/trace/HC-PKG-2026-000014';
const LABEL_B = 'http://localhost:4173/trace/HC-PKG-2026-000015';

function fakeStream() {
  const tracks = [{ stop: vi.fn() }, { stop: vi.fn() }]; // e.g. two tracks: every one must stop
  return { tracks, getTracks: () => tracks };
}

let streams;
let getUserMedia;

beforeEach(() => {
  streams = [];
  getUserMedia = vi.fn(async () => {
    const stream = fakeStream();
    streams.push(stream);
    return stream;
  });
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });

  // A playing video with a picture.
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  Object.defineProperty(HTMLMediaElement.prototype, 'readyState', { configurable: true, get: () => 4 });
  Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', { configurable: true, get: () => 640 });
  Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', { configurable: true, get: () => 480 });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
    getImageData: () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 }),
  });

  decode.mockReset();
  decode.mockReturnValue(null); // nothing in view until a test says otherwise
});

afterEach(() => {
  vi.restoreAllMocks();
  delete HTMLMediaElement.prototype.readyState;
  delete HTMLVideoElement.prototype.videoWidth;
  delete HTMLVideoElement.prototype.videoHeight;
});

const renderPage = () =>
  render(
    <MemoryRouter>
      <ConsumerVerificationPage />
    </MemoryRouter>,
  );

const allTracksStopped = (stream) => stream.tracks.every((track) => track.stop.mock.calls.length >= 1);

describe('Scan QR Code', () => {
  it('shows a visible Scan QR Code button next to the manual form', () => {
    renderPage();
    expect(screen.getByRole('button', { name: 'Scan QR Code' })).toBeVisible();
    expect(screen.getByLabelText('Package code or QR ID')).toBeInTheDocument();
  });

  it('opens the camera, detects a HoneyChain QR, stops the camera, closes, and runs the existing verification', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    expect(getUserMedia.mock.calls[0][0]).toMatchObject({ video: expect.anything(), audio: false });
    expect(await screen.findByTestId('qr-camera-preview')).toBeInTheDocument();
    // Live preview is attached to the stream.
    expect(screen.getByTestId('qr-camera-preview').srcObject).toBe(streams[0]);
    expect(allTracksStopped(streams[0])).toBe(false); // camera is live while scanning

    decode.mockReturnValue({ data: LABEL_A });

    await waitFor(() => expect(screen.getByTestId('trace-report')).toHaveTextContent('HC-PKG-2026-000014'));
    expect(allTracksStopped(streams[0])).toBe(true); // every track stopped
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    // The scanned code lands in the same input the manual flow uses.
    expect(screen.getByLabelText('Package code or QR ID')).toHaveValue('HC-PKG-2026-000014');
  });

  it('verifies QR A and QR B as different packages', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    decode.mockReturnValue({ data: LABEL_A });
    await waitFor(() => expect(screen.getByTestId('trace-report')).toHaveTextContent('HC-PKG-2026-000014'));

    decode.mockReturnValue(null); // the camera is now pointed at a different jar
    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));
    decode.mockReturnValue({ data: LABEL_B });
    await waitFor(() => expect(screen.getByTestId('trace-report')).toHaveTextContent('HC-PKG-2026-000015'));

    expect(streams).toHaveLength(2);
    streams.forEach((stream) => expect(allTracksStopped(stream)).toBe(true));
  });

  it('shows "Invalid HoneyChain QR Code" for any other QR, with the camera off and no verification', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    decode.mockReturnValue({ data: 'https://example.com/some-other-qr' });

    expect(await screen.findByText('Invalid HoneyChain QR Code')).toBeInTheDocument();
    expect(allTracksStopped(streams[0])).toBe(true);
    expect(screen.queryByTestId('trace-report')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('explains a denied permission and keeps manual verification available', async () => {
    getUserMedia.mockRejectedValueOnce(Object.assign(new Error('denied'), { name: 'NotAllowedError' }));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    expect(await screen.findByText(/Camera access was denied/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    // Manual verification still works exactly as before.
    await user.type(screen.getByLabelText('Package code or QR ID'), 'HC-PKG-2026-000014');
    await user.click(screen.getByRole('button', { name: 'Verify' }));
    expect(screen.getByTestId('trace-report')).toHaveTextContent('HC-PKG-2026-000014');
  });

  it('tells the person when there is no camera or the browser cannot open one', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    expect(await screen.findByText(/cannot open the camera here/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Scan QR Code' })).toBeEnabled();
  });

  it('stops every camera track when the scanner is cancelled', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    await screen.findByTestId('qr-camera-preview');
    expect(allTracksStopped(streams[0])).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    // Synchronously released — not left to the dialog's exit animation.
    expect(allTracksStopped(streams[0])).toBe(true);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByTestId('trace-report')).not.toBeInTheDocument();
  });

  it('stops every camera track when closed with the X or Escape', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(allTracksStopped(streams[0])).toBe(true);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));
    await user.keyboard('{Escape}');
    expect(allTracksStopped(streams[1])).toBe(true);
  });

  it('stops the camera when the page is left while scanning (unmount)', async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    await screen.findByTestId('qr-camera-preview');

    unmount();
    expect(allTracksStopped(streams[0])).toBe(true);
  });

  it('releases a camera that is granted after the scanner was already closed', async () => {
    let grant;
    getUserMedia.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          grant = () => {
            const stream = fakeStream();
            streams.push(stream);
            resolve(stream);
          };
        }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Scan QR Code' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'Cancel' })); // closed while the prompt is open

    await act(async () => {
      grant();
    });
    expect(allTracksStopped(streams[0])).toBe(true);
  });

  it('keeps manual verification exactly as it was', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole('button', { name: 'Verify' })).toBeDisabled();
    await user.type(screen.getByLabelText('Package code or QR ID'), 'http://localhost:4173/trace/HC-PKG-2026-000014');
    await user.click(screen.getByRole('button', { name: 'Verify' }));
    expect(screen.getByTestId('trace-report')).toHaveTextContent('HC-PKG-2026-000014');
    expect(getUserMedia).not.toHaveBeenCalled(); // manual entry never touches the camera
  });
});
