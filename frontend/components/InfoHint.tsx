'use client';

import { Popover, Text, ActionIcon, Box } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';

/**
 * Ayuda contextual discreta: un icono (i) que al hacer clic abre un popover explicando qué es
 * la métrica/panel y cómo leerlo. Pensado para que cualquiera entienda el dashboard sin docs.
 * Se usa embebido en SectionHeader (help) y StatCard (hint), y de forma suelta donde haga falta.
 */
export function InfoHint({ title, body, size = 14 }: { title?: string; body: string; size?: number }) {
  return (
    <Popover width={280} position="top" withArrow shadow="md" trapFocus>
      <Popover.Target>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          radius="xl"
          aria-label={title ? `Ayuda: ${title}` : 'Ayuda'}
          onClick={(e) => e.stopPropagation()}
          style={{ cursor: 'pointer' }}
        >
          <IconInfoCircle size={size} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown onClick={(e) => e.stopPropagation()}>
        {title && (
          <Text size="xs" fw={700} c="brand.4" mb={4}>
            {title}
          </Text>
        )}
        <Text size="xs" c="dimmed" lh={1.5}>
          {body}
        </Text>
      </Popover.Dropdown>
    </Popover>
  );
}

/** Bloque de texto explicativo dentro de un popover de guía más grande (para listas). */
export function HelpRow({ term, desc }: { term: string; desc: string }) {
  return (
    <Box mb={8}>
      <Text size="xs" fw={700}>
        {term}
      </Text>
      <Text size="xs" c="dimmed" lh={1.45}>
        {desc}
      </Text>
    </Box>
  );
}
