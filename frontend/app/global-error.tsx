'use client';

/**
 * Error boundary GLOBAL (Next.js): sustituye al layout raíz entero cuando éste falla,
 * así que aquí NO hay MantineProvider — sólo HTML plano con el fondo oscuro del theme.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="es">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#0b0f1a',
          color: '#e6e9f0',
          fontFamily: 'Inter, system-ui, sans-serif',
        }}
      >
        <div style={{ textAlign: 'center', padding: 32, maxWidth: 460 }}>
          <h2 style={{ margin: '0 0 12px' }}>Algo salió mal</h2>
          <p style={{ color: '#8893a8', fontSize: 14, lineHeight: 1.5 }}>
            El dashboard encontró un error crítico. Puedes reintentar; si persiste, recarga la
            página.
          </p>
          {error.digest && (
            <p style={{ color: '#8893a8', fontSize: 12, fontFamily: 'monospace' }}>
              ref: {error.digest}
            </p>
          )}
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: 8,
              padding: '10px 22px',
              borderRadius: 8,
              border: '1px solid rgba(22,214,127,0.4)',
              background: 'rgba(22,214,127,0.12)',
              color: '#16d67f',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Reintentar
          </button>
        </div>
      </body>
    </html>
  );
}
