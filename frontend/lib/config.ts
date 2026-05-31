// Base del backend. Configurable por entorno (NEXT_PUBLIC_API_BASE).
// En despliegue, nginx sirve front y back en el mismo origen ⇒ "" (rutas relativas).
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';
