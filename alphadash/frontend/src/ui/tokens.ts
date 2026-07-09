// Minimal design tokens (S0.4). Full theming is out of scope until later sessions — these exist
// so primitives share one palette/spacing scale instead of scattering magic values.

export const color = {
  text: "#1a2233",
  textMuted: "#5b6474",
  surface: "#ffffff",
  surfaceSubtle: "#f4f6fa",
  border: "#d7dce5",
  info: "#e8f1fd",
  infoText: "#1d4f91",
  positive: "#e6f6ec",
  positiveText: "#176639",
  caution: "#fdf3e0",
  cautionText: "#8a5a00",
  danger: "#b4232a",
  dangerSubtle: "#fbeaea",
  primary: "#1d4f91",
} as const;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const radius = { sm: 6, md: 10, lg: 14, pill: 999 } as const;

export const font = {
  family: "system-ui, sans-serif",
  sizeSm: 13,
  sizeMd: 15,
  sizeLg: 18,
} as const;
