export type ThemeName = "dark" | "light";

// v2: bumped when the default theme changed from dark to light so browsers
// with a pre-redesign cached "dark" value under the old key don't silently
// override the new default forever.
const STORAGE_KEY = "aiva.theme.v2";

const DEFAULT_THEME: ThemeName = "light";

export function loadTheme(): ThemeName {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") {
      return stored;
    }
  } catch {
    return DEFAULT_THEME;
  }
  return DEFAULT_THEME;
}

export function applyTheme(theme: ThemeName): void {
  document.documentElement.setAttribute("data-theme", theme);
}

export function saveTheme(theme: ThemeName): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    return;
  }
}
