# @forge/patches

Typed `EditorAction` union, `applyAction(artifacts, action)` with typed
inverses, and the `normalize()` round-trip-identity function. The
load-bearing primitive for Tentoro Forge's mutation model — both the
editor and the LLM peer patcher commit through this package.

```ts
import { applyAction, type EditorAction } from "@forge/patches";
```
