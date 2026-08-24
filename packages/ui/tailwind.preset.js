module.exports = {
  content: [],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        abyss: "var(--abyss)",
        hull: "var(--hull)",
        steel: "var(--steel)",
        signal: "var(--signal)",
        "signal-text": "var(--signal-text)",
        "signal-dim": "var(--signal-dim)",
        ember: "var(--ember)",
        mist: "var(--mist)",
        haze: "var(--haze)",
        danger: "var(--danger)",
        warning: "var(--warning)",
        success: "var(--success)",
      },
      fontFamily: {
        display: "var(--font-display)",
        body: "var(--font-body)",
        mono: "var(--font-mono)",
      },
      transitionDuration: {
        instant: "var(--dur-instant)",
        quick: "var(--dur-quick)",
        base: "var(--dur-base)",
        slow: "var(--dur-slow)",
      },
    },
  },
};
