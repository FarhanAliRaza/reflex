import { getContext } from "svelte";

import { REFLEX_RUNTIME } from "$lib/reflex/runtime.svelte.js";

export function getReflexRuntime() {
  return getContext(REFLEX_RUNTIME);
}
