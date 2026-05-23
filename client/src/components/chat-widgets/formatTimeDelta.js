const NEAR_ZERO_THRESHOLD_S = 0.005;

export function formatTimeDelta(seconds, { signed = true, approximate = false } = {}) {
  if (seconds == null || Number.isNaN(seconds)) return null;
  if (Math.abs(seconds) < NEAR_ZERO_THRESHOLD_S) return signed ? "≈0s" : "0s";
  const sign = signed ? (seconds >= 0 ? "+" : "−") : (seconds < 0 ? "−" : "");
  const magnitude = Math.abs(seconds);
  const formatted = magnitude < 0.1 ? magnitude.toFixed(3) : magnitude.toFixed(2);
  return `${approximate ? "~" : ""}${sign}${formatted}s`;
}

export function formatTimeMagnitude(seconds, { approximate = false } = {}) {
  return formatTimeDelta(seconds, { signed: false, approximate });
}
