<script>
  import "$/styles/__reflex_global_styles.css";

  import { onMount, setContext } from "svelte";

  import {
    clientStorage,
    defaultColorMode,
    exceptionStateName,
    initialState,
    stateName,
  } from "$lib/reflex/generated/context.js";
  import { REFLEX_RUNTIME, ReflexRuntime } from "$lib/reflex/runtime.svelte.js";

  const runtime = new ReflexRuntime({
    initialState,
    clientStorage,
    stateName,
    exceptionStateName,
    defaultColorMode,
  });

  setContext(REFLEX_RUNTIME, runtime);

  onMount(() => runtime.mount());
</script>

<div
  class={`radix-themes ${runtime.resolvedColorMode}`}
  data-is-root-theme="true"
  data-accent-color="blue"
  data-gray-color="slate"
  data-has-background="true"
  data-panel-background="translucent"
  data-radius="medium"
  data-scaling="100%"
>
  <slot />
</div>
