import en from "./en.json";
import zh from "./zh.json";

const dict = { en, zh };

export function getInitialLang() {
  // `autoeh_lang` is the legacy key kept for continuity with pre-rebrand
  // browsers; new writes only ever touch the ZingLib key.
  const fromStorage = (localStorage.getItem("zgl_lang") || localStorage.getItem("autoeh_lang") || "").toLowerCase();
  if (fromStorage === "en" || fromStorage === "zh") return fromStorage;
  return "zh";
}

export function setLang(lang) {
  const next = lang === "en" ? "en" : "zh";
  localStorage.setItem("zgl_lang", next);
  try {
    localStorage.removeItem("autoeh_lang");
  } catch {
    // Storage can be unavailable in private modes; the preference is optional.
  }
  return next;
}

export function t(lang, key, vars = {}) {
  const base = dict[lang] || dict.zh;
  const fallback = dict.en;
  let text = base[key] || fallback[key] || key;
  Object.entries(vars).forEach(([k, v]) => {
    text = text.replaceAll(`{${k}}`, String(v));
  });
  return text;
}
