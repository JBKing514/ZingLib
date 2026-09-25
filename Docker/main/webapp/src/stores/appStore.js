import { computed, ref } from "vue";
import { defineStore } from "pinia";
import {
  changePassword,
  changePasswordWithRecoveryCode,
  deleteAccount,
  getAuthBootstrap,
  getCsrfToken,
  getMe,
  getSetupStatus,
  login,
  logout,
  registerAdmin,
  setCsrfToken,
  updateProfile,
  verifyPassword,
} from "../api";
import { useToastStore } from "./useToastStore";
import { getInitialLang, t as translate } from "../i18n";
import { apiErrorMessage } from "../utils/apiErrors";

export const useAppStore = defineStore("app", () => {
  const toast = useToastStore();
  // This store has no `t` prop of its own (it is not a component), but the auth
  // gate renders `authError` verbatim, so it needs the same translator the rest
  // of the shell uses -- imported straight from i18n to avoid a store cycle.
  const t = (key, vars = {}) => translate(getInitialLang(), key, vars);

  const showAuthGate = ref(false);
  const showSetupWizard = ref(false);
  const authConfigured = ref(true);
  const authSubmitting = ref(false);
  const authError = ref("");
  const authReady = ref(false);
  const authUser = ref({ uid: "", username: "", role: "" });
  // `username` mirrors the account and is **display-only** in the panel: the
  // rename takes its new name from its own dialog, so an input that happens to
  // be bound to this ref can never move the identity (see renameAccount). The
  // dialog fields live in the view; only what has to survive a remount is here,
  // so this ref stays a mirror of the account, not a scratch pad for forms.
  const accountForm = ref({ username: "" });

  const isRecoveryMode = computed(() => String(authUser.value.role || "").toLowerCase() === "recovery");

  let _t = (k) => k;
  let _afterAuthOk = null;
  let _afterLogout = null;

  function init(deps = {}) {
    if (typeof deps.t === "function") _t = deps.t;
    if (typeof deps.afterAuthOk === "function") _afterAuthOk = deps.afterAuthOk;
    if (typeof deps.afterLogout === "function") _afterLogout = deps.afterLogout;
  }

  async function bootstrap() {
    authError.value = "";
    authReady.value = false;
    showAuthGate.value = false;
    try {
      const b = await getAuthBootstrap();
      authConfigured.value = !!b.configured;
      if (!b.db_ready) {
        showAuthGate.value = false;
        showSetupWizard.value = true;
      } else if (b.configured) {
        const me = await getMe();
        authUser.value = me.user || {};
        accountForm.value.username = String(authUser.value.username || "");
        const csrf = await getCsrfToken();
        setCsrfToken(csrf.csrf_token || "");
        const st = await getSetupStatus();
        showSetupWizard.value = !st.initialized;
        showAuthGate.value = false;
      } else {
        showAuthGate.value = false;
        showSetupWizard.value = true;
      }
    } catch (e) {
      authConfigured.value = true;
      showAuthGate.value = true;
      authError.value = apiErrorMessage(e, t);
    } finally {
      authReady.value = true;
    }
  }

  function onAuthRequiredEvent() {
    showAuthGate.value = true;
    authError.value = _t("auth.required");
    setCsrfToken("");
  }

  async function registerNow(payload) {
    authSubmitting.value = true;
    authError.value = "";
    try {
      const res = await registerAdmin(payload?.username, payload?.password);
      authUser.value = res.user || {};
      accountForm.value.username = String(authUser.value.username || "");
      setCsrfToken(res?.session?.csrf_token || "");
      authConfigured.value = true;
      showAuthGate.value = false;
      showSetupWizard.value = true;
      if (_afterAuthOk) await _afterAuthOk();
    } catch (e) {
      authError.value = apiErrorMessage(e, t);
    } finally {
      authSubmitting.value = false;
    }
  }

  async function loginNow(payload) {
    authSubmitting.value = true;
    authError.value = "";
    try {
      const res = await login(payload?.username, payload?.password);
      setCsrfToken(res?.session?.csrf_token || "");
      if (res.recovery_mode) {
        authUser.value = res.user || {};
        showAuthGate.value = false;
        if (_afterAuthOk) await _afterAuthOk();
        return;
      }
      const me = await getMe();
      authUser.value = me.user || {};
      accountForm.value.username = String(authUser.value.username || "");
      const st = await getSetupStatus();
      showSetupWizard.value = !st.initialized;
      showAuthGate.value = false;
      if (_afterAuthOk) await _afterAuthOk();
    } catch (e) {
      authError.value = apiErrorMessage(e, t);
    } finally {
      authSubmitting.value = false;
    }
  }

  async function logoutNow() {
    try {
      await logout();
    } catch {
      // ignore
    }
    setCsrfToken("");
    showAuthGate.value = true;
    if (_afterLogout) _afterLogout();
  }

  /**
   * Verify the *current* password against the account that is logged in.
   *
   * Every account-level action below is gated on this: an identity change (the
   * username keys the login form, the recovery record and every stored session)
   * and a destructive change (delete) both need a fresh credential check, and a
   * single click is not one. Shared here so the three flows cannot drift into
   * three slightly different gates.
   *
   * Returns true on success, false on failure -- and the failure is already
   * surfaced as a toast, so callers only branch, never re-report.
   */
  async function verifyCurrentPassword(password) {
    const currentName = String(authUser.value.username || "").trim();
    const typed = String(password || "").trim();
    if (!typed) {
      toast.warning(_t("auth.profile.confirm_required"));
      return false;
    }
    try {
      await verifyPassword(currentName, typed);
      return true;
    } catch (e) {
      toast.warning(apiErrorMessage(e, t));
      return false;
    }
  }

  /**
   * Rename the account, but only after the current password has been verified.
   *
   * The username is display-only in the panel and arrives here as an argument
   * (the dialog's own field), so a rename can never happen as a side effect of
   * editing a bound input. `currentPassword` is the value typed into the
   * dialog's gate field -- verified against the *current* username before the
   * new name is written, so it cannot be satisfied by the new name's password.
   */
  async function renameAccount(currentPassword, nextUsername) {
    const nextName = String(nextUsername || "").trim();
    const currentName = String(authUser.value.username || "").trim();
    if (!nextName) {
      toast.warning(_t("auth.profile.username_required"));
      return false;
    }
    if (nextName === currentName) {
      toast.warning(_t("auth.profile.updated"));
      return true;
    }
    if (!(await verifyCurrentPassword(currentPassword))) return false;
    try {
      const res = await updateProfile(nextName);
      authUser.value = res.user || authUser.value;
      accountForm.value.username = String(authUser.value.username || "");
      toast.success(_t("auth.profile.updated"));
      return true;
    } catch (e) {
      toast.warning(apiErrorMessage(e, t));
      return false;
    }
  }

  /**
   * Change the password, gated on the current one -- or on a recovery code.
   *
   * A separate "verify" step (the dialog's first page) proves the old password
   * before the new one is even typed, so the two-field mismatch can only be
   * reported after the gate is open. The account is signed out afterwards: the
   * stored session was issued under the old credential.
   *
   * `opts.useRecoveryCode` swaps the gate: the value typed into the gate field
   * is then a burn-after-use recovery code, the server writes the password
   * without ever seeing the old one, and every session of that account is
   * revoked -- including this one. The user is therefore signed out on this
   * path too, for a different reason: there is no longer a session to keep.
   * That is the honest outcome, and regaining control is what the flow was for.
   */
  async function changeAccountPassword(currentPassword, newPassword, newPassword2, opts = {}) {
    if (String(newPassword || "") !== String(newPassword2 || "")) {
      toast.warning(_t("auth.profile.password_mismatch"));
      return false;
    }
    const username = String(authUser.value.username || "").trim();
    if (opts && opts.useRecoveryCode) {
      const code = String(currentPassword || "").trim();
      if (!code) {
        toast.warning(_t("auth.profile.recovery_code_required"));
        return false;
      }
      try {
        await changePasswordWithRecoveryCode(username, code, String(newPassword || ""));
        toast.success(_t("auth.profile.password_changed"));
        await logoutNow();
        return true;
      } catch (e) {
        toast.warning(apiErrorMessage(e, t));
        return false;
      }
    }
    if (!(await verifyCurrentPassword(currentPassword))) return false;
    try {
      // Recovery mode has no old password to send (the server issues the
      // recovery session without one), and the recovery flow already proved
      // itself by getting in. The normal path sends what was just verified.
      const isRecovery = String(authUser.value.role || "").toLowerCase() === "recovery";
      await changePassword(
        isRecovery ? "" : String(currentPassword || ""),
        String(newPassword || ""),
        username,
      );
      toast.success(_t("auth.profile.password_changed"));
      await logoutNow();
      return true;
    } catch (e) {
      toast.warning(apiErrorMessage(e, t));
      return false;
    }
  }

  /**
   * Delete the account, then hand the instance back to the setup wizard.
   *
   * The backend clears `initialized` / `user_configured` alongside the row, so
   * the *only* honest thing to show afterwards is the wizard asking for a new
   * administrator. Showing the login gate instead would strand the user on a
   * form that has nothing left to authenticate against -- which is exactly what
   * `logoutNow()` does, so this path deliberately does not use it: it drops the
   * session, then re-runs `bootstrap()`, whose `configured === false` branch is
   * what raises the wizard.
   */
  async function deleteAccountNow(password) {
    const pwd = String(password || "").trim();
    if (!pwd) {
      toast.warning(_t("auth.profile.confirm_required"));
      return false;
    }
    try {
      await deleteAccount(pwd);
      toast.success(_t("auth.profile.deleted"));
    } catch (e) {
      toast.warning(apiErrorMessage(e, t));
      return false;
    }
    // Session is gone server-side; clear the client's copy before asking the
    // server what the instance looks like now.
    setCsrfToken("");
    authUser.value = {};
    accountForm.value = { username: "" };
    showAuthGate.value = false;
    if (_afterLogout) _afterLogout();
    await bootstrap();
    // Belt and braces: if the bootstrap round trip failed (server hiccup) the
    // instance is still unconfigured, so the wizard is the correct fallback
    // rather than a login form with no account behind it.
    if (!showSetupWizard.value && !showAuthGate.value) showSetupWizard.value = true;
    return true;
  }

  function openSetupWizardManual() {
    showSetupWizard.value = true;
  }

  function closeSetupWizard() {
    showSetupWizard.value = false;
  }

  return {
    showAuthGate,
    showSetupWizard,
    authConfigured,
    authSubmitting,
    authError,
    authReady,
    authUser,
    isRecoveryMode,
    accountForm,
    init,
    bootstrap,
    onAuthRequiredEvent,
    registerNow,
    loginNow,
    logoutNow,
    verifyCurrentPassword,
    renameAccount,
    changeAccountPassword,
    deleteAccountNow,
    openSetupWizardManual,
    closeSetupWizard,
  };
});
