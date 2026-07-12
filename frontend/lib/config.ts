// Base del backend. Configurable por entorno (NEXT_PUBLIC_API_BASE).
// En despliegue, nginx sirve front y back en el mismo origen ⇒ "" (rutas relativas).
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';

// Superficie pública read-only (PRD-010). Build-time: Next sustituye NEXT_PUBLIC_READ_ONLY
// por literal en `npm run build`; sin la variable (dev local), superficie completa.
// El 401 del backend sigue siendo el límite de seguridad; esto es UX y honestidad.
export const READ_ONLY = process.env.NEXT_PUBLIC_READ_ONLY === '1';
