"""The QR label itself.

One function, one job: turn the string a package carries into an SVG. SVG rather
than PNG because a label is printed at whatever size the printer has, and vector
output stays sharp — and because it needs no imaging library at all.

The image is generated from the *stored* payload, never from a value computed at
render time, so the code in the label and the record of it cannot drift apart.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger("honeychain.blockchain")

#: Error-correction level. ``M`` is the usual choice for a printed label: it
#: tolerates a scuffed print or a fingerprint without making the modules so
#: small that a phone camera struggles.
_QR_ERROR_CORRECTION = None  # set lazily below, so importing qrcode is optional

#: The prefix of a package's public QR identity. The identity is derived from the
#: package it belongs to — never generated, never random, never stored twice —
#: so the same package always has the same QR id, whatever happens to the label.
QR_ID_PREFIX = "QR-"


def qr_identifier(package_code: str) -> str:
    """The stable public id of the code on a package's label.

    ``HC-PKG-2026-000001`` → ``QR-HC-PKG-2026-000001``. It is a pure function of
    the package code, which is what makes it stable: a refresh, a reprint or a
    second scan of the same jar cannot produce a different one.
    """
    return f"{QR_ID_PREFIX}{(package_code or '').strip()}"


def package_code_from_qr(code: str) -> str:
    """The package code behind a scanned value.

    Accepts either the QR id (``QR-HC-PKG-…``) or the package code itself, so a
    label printed before this convention existed, and a link that carries the
    package code directly, both resolve to the same package.
    """
    value = (code or "").strip()
    if value.upper().startswith(QR_ID_PREFIX):
        return value[len(QR_ID_PREFIX):]
    return value


def qr_svg(payload: str, *, border: int = 2) -> str:
    """The QR for ``payload`` as an inline SVG string.

    A payload that cannot be encoded returns a small placeholder SVG rather than
    raising: the QR is a convenience on a read path, and a screen that cannot
    draw it should still show the link itself, which is what the API returns
    beside this.
    """
    if not payload:
        return _empty_svg("No QR issued")
    try:
        import qrcode  # imported here: the label is the only thing that needs it
        import qrcode.image.svg
        from qrcode.constants import ERROR_CORRECT_M

        image = qrcode.make(
            payload,
            image_factory=qrcode.image.svg.SvgPathImage,
            error_correction=ERROR_CORRECT_M,
            border=border,
        )
        buffer = io.BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode("utf-8")
    except Exception:  # pragma: no cover - an encoder that is unavailable
        logger.warning("QR rendering failed", exc_info=True)
        return _empty_svg("QR unavailable")


def _empty_svg(message: str) -> str:  # pragma: no cover - placeholder path
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">'
        '<rect width="160" height="160" fill="#ffffff" stroke="#d1d5db"/>'
        f'<text x="80" y="84" font-size="11" text-anchor="middle" fill="#6b7280">{message}</text>'
        "</svg>"
    )


__all__ = ["qr_svg"]
