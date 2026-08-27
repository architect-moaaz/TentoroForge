# @forge/registry

The canonical component registry for Tentoro Forge. Exports typed `RegistryEntry` / `PropDescriptor` / `SlotRule` shapes, a `starterRegistry` covering the 12 highest-leverage components for CRUD-class apps (spec §13.1–13.4), and a `registryDigest()` helper that serialises any registry into a compact, token-budget-friendly string fed to the LLM's `writeArtifacts` system prompt. This is the single source of truth consumed by the palette, properties panel, renderer dispatch, and the AI constraint layer.

```ts
import { starterRegistry, registryDigest, type RegistryEntry } from "@forge/registry";
```
