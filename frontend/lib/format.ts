// Locale único de formateo numérico del dashboard. Todos los formatters money/num del design
// system ya usan 'en-US' explícito (separador de miles ",", decimal "."); los toLocaleString()
// sin argumento dependían del navegador y podían renderizar "1.234" vs "1,234" en la misma vista.
export const NUM_LOCALE = 'en-US';
// Convención única del dashboard: números en-US (NUM_LOCALE), horas es-MX (TIME_LOCALE).
export const TIME_LOCALE = 'es-MX';
