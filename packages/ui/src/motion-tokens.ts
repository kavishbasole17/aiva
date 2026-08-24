export const SPRING = { stiffness: 260, damping: 26, mass: 0.9 } as const;

export const DURATIONS = {
  instant: 100,
  quick: 180,
  base: 280,
  slow: 420,
} as const;

export const EASE_OUT: [number, number, number, number] = [0.16, 1, 0.3, 1];
export const EASE_IN_OUT: [number, number, number, number] = [0.65, 0, 0.35, 1];
