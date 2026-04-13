<script>
  export let error;
</script>

<svelte:head>
  <title>Reflex Error</title>
</svelte:head>

<main
  style="min-height: 100vh; display: grid; place-items: center; font-family: system-ui, sans-serif; padding: 2rem;"
>
  <section style="max-width: 48rem; width: 100%;">
    <h1 style="font-size: 2rem; margin-bottom: 1rem;">
      An error occurred while rendering this page.
    </h1>
    <pre
      style="white-space: pre-wrap; word-break: break-word; background: #f5f5f5; padding: 1rem; border-radius: 0.5rem;"
    >{error?.name}: {error?.message}
{error?.stack}</pre>
  </section>
</main>
