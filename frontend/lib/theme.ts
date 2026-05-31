import { createTheme, type MantineColorsTuple } from '@mantine/core';

/**
 * Sistema de diseño inspirado en Bitstamp: limpio, moderno, fresco pero tecnológico.
 * Verde de marca fresco sobre slate profundo cool (dark), tipografía geométrica (Outfit
 * en títulos / Inter en cuerpo) y numéricos en monospace tabular. Recolorea la escala
 * `dark` de Mantine a slate cool (no el gris azulado por defecto) para que fondo, cards,
 * bordes, tablas y badges queden cohesionados sin estilos ad-hoc.
 */

// Verde Bitstamp — color primario / identidad de marca (fresco, tecnológico).
const brand: MantineColorsTuple = [
  '#E3FBEF', // 0
  '#BDF4D8', // 1
  '#90ECBE', // 2
  '#5DE3A2', // 3
  '#33DB8E', // 4
  '#16D67F', // 5  ← verde principal
  '#0CBE6F', // 6  filled / hover
  '#07A05D', // 7
  '#057E49', // 8
  '#045B35', // 9
];

// Escala slate cool profunda. Mantine la usa así en dark: [7]=fondo body, [6]=card/paper,
// [5]=hover, [4]=bordes, [0-2]=texto. Sobrescribirla recolorea toda la app.
const dark: MantineColorsTuple = [
  '#E6ECF6', // 0  texto más claro
  '#AEB9CE', // 1
  '#8B97AE', // 2  texto dimmed (label técnico)
  '#5C6982', // 3  slate medio
  '#232E3D', // 4  bordes
  '#18212E', // 5  superficie elevada / hover
  '#111824', // 6  card / paper (panel)
  '#0A0E16', // 7  fondo body (base)
  '#070A11', // 8
  '#04060B', // 9
];

// Acento cian para series de datos secundarias (charts), fresco y tecnológico.
const aqua: MantineColorsTuple = [
  '#E0FBFB',
  '#BAF2F4',
  '#8AE7EB',
  '#54DBE1',
  '#2BD0D8',
  '#13C6CF', // 5
  '#0BB0B9',
  '#06939B',
  '#04747B',
  '#02545A',
];

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: { dark: 5, light: 6 },
  colors: { brand, dark, aqua },
  white: '#F4F7FC',
  black: '#0B0F1A',
  fontFamily:
    'var(--font-inter), -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  fontFamilyMonospace:
    'var(--font-mono), ui-monospace, SFMono-Regular, Menlo, monospace',
  headings: {
    fontFamily:
      'var(--font-outfit), var(--font-inter), -apple-system, BlinkMacSystemFont, sans-serif',
    fontWeight: '600',
  },
  defaultRadius: 'md',
  // Objetos planos (no `Component.extend`, que es client-only y rompe el build SSR).
  components: {
    Card: { defaultProps: { radius: 'lg', withBorder: true, padding: 'lg' } },
    Table: { defaultProps: { verticalSpacing: 7, horizontalSpacing: 'md' } },
    Badge: { defaultProps: { radius: 'sm', fw: 600 } },
  },
});
