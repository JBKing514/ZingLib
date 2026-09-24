/**
 * Turn an API failure into something worth showing a user.
 *
 * The API answers a rejected credential with a structured detail --
 * `{code, field, min_length, message}` (see `routers/auth.py`) -- so the UI can
 * say "the password must be at least 8 characters" in the reader's own language.
 * Anything else is passed through as its string detail.
 *
 * Never stringify a non-string detail. `String(err)` on an AxiosError produces
 * "AxiosError: Request failed with status code 400", and a raw error object
 * rendered onto the screen is exactly what reads as an internal traceback.
 */

const CODE_KEYS = {
  password_too_short: "auth.password_too_short",
  username_too_short: "auth.username_too_short",
};

// Mirrors `webapi/services/auth_service.py` (MIN_PASSWORD_LENGTH /
// MIN_USERNAME_LENGTH). The server is still the authority -- it sends
// `min_length` back with the rejection -- so these only drive the client-side
// pre-check that keeps the obvious mistake from needing a round trip at all.
export const MIN_PASSWORD_LENGTH = 8;
export const MIN_USERNAME_LENGTH = 3;

export function apiErrorMessage(err, t, fallbackKey = "auth.request_failed") {
  const detail = err?.response?.data?.detail;
  const status = Number(err?.response?.status || 0);
  const translate = typeof t === "function" ? t : null;

  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const key = CODE_KEYS[String(detail.code || "")];
    if (key && translate) {
      const min = Number(detail.min_length || 0);
      return min ? translate(key, { n: min }) : translate(key);
    }
    const message = String(detail.message || "").trim();
    if (message) return message;
  }
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (translate) return translate(fallbackKey, { status: status || 0 });
  return status ? `HTTP ${status}` : "request failed";
}

export default apiErrorMessage;
