/**
 * A fresh id for one attempt at something (an idempotency key, mainly).
 *
 * `crypto.randomUUID()` only exists in a secure context -- HTTPS, or
 * localhost. This shop runs over plain HTTP until it has a domain and a
 * certificate, so calling it directly throws before the request it was
 * meant to tag ever goes out, and the caller sees a generic failure with no
 * network activity to explain it. `crypto.getRandomValues()` has no such
 * restriction, so it is what actually works here -- randomUUID is only
 * tried first because it is spec-guaranteed correct where it is available.
 */
export function randomId() {
  if (typeof crypto?.randomUUID === 'function') {
    try {
      return crypto.randomUUID();
    } catch {
      // Falls through to the manual build below.
    }
  }

  const bytes = new Uint8Array(16);
  if (typeof crypto?.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
  } else {
    // No Web Crypto at all. Still fine for an idempotency key: it only has
    // to differ between attempts, not resist an attacker guessing it.
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx

  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
