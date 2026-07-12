'use client';

import { Button, Stack, Text, Title } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

/**
 * Error boundary de ruta (Next.js): captura errores de render dentro del layout raíz
 * (con MantineProvider disponible) y ofrece reintento sin recargar la página.
 */
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <Stack align="center" justify="center" mih="70vh" gap="md" p="xl">
      <IconAlertTriangle size={40} color="var(--mantine-color-red-5)" />
      <Title order={3}>Algo salió mal</Title>
      <Text c="dimmed" size="sm" ta="center" maw={420}>
        El dashboard encontró un error inesperado. Puedes reintentar; si persiste, recarga la
        página.
      </Text>
      {error.digest && (
        <Text size="xs" c="dimmed" ff="monospace">
          ref: {error.digest}
        </Text>
      )}
      <Button color="brand" onClick={reset}>
        Reintentar
      </Button>
    </Stack>
  );
}
