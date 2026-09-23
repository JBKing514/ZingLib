import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import vuetify from "vite-plugin-vuetify";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(process.env.VITE_APP_VERSION || process.env.npm_package_version || ""),
  },
  plugins: [
    vue(),
    vuetify({ autoImport: true }),
    VitePWA({
      registerType: "autoUpdate",
      workbox: {
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        globIgnores: ["**/version.json"],
      },
      manifest: {
        name: "ZingLib",
        short_name: "ZingLib",
        description: "ZingLib local library dashboard",
        theme_color: "#000000",
        background_color: "#000000",
        display: "standalone",
        start_url: "/#/dashboard",
        icons: [
          {
            src: "/ico/ZingLibLogo_128.png",
            sizes: "128x128",
            type: "image/png",
          },
          {
            src: "/ico/ZingLibLogo_256.png",
            sizes: "256x256",
            type: "image/png",
          },
          {
            src: "/ico/ZingLibLogo_512.png",
            sizes: "512x512",
            type: "image/png",
          },
        ],
      },
    }),
  ],
  build: {
    outDir: "dist",
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8501",
    },
  },
});
