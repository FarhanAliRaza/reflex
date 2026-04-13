import { fileURLToPath, URL } from "url";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: Number.parseInt(process.env.PORT || "3000", 10),
    hmr: true,
    watch: {
      ignored: [
        "**/.web/backend/**",
        "**/.web/reflex.install_frontend_packages.cached",
      ],
    },
  },
  resolve: {
    alias: [
      {
        find: "$",
        replacement: fileURLToPath(new URL("./", import.meta.url)),
      },
      {
        find: "@",
        replacement: fileURLToPath(new URL("./public", import.meta.url)),
      },
    ],
  },
});
