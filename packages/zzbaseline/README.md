# @tentoroforge/engine

Self-contained rendering engine for Tentoro Forge generated apps.
Reads page schemas at runtime, dispatches through the component library,
applies design tokens. One dependency for generated Next.js apps.

```tsx
import { Engine, EngineProvider } from "@tentoroforge/engine";

<EngineProvider designSpec={designSpec} navFlow={navFlow}>
  <Engine schema={pageSchema} apiBaseUrl="/" />
</EngineProvider>
```

The engine works in two modes via the same code path:
- **JIT** — client-side rendering (editor canvas + browser preview)
- **SSR** — server-side rendering (generated app's initial paint)
