import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync, readdirSync } from "node:fs";
export default defineConfig({
  plugins: [
    react(),
    {
      name: "runtime-license-notices",
      generateBundle() {
        for (const dir of ["cmaps", "standard_fonts", "wasm"]) {
          for (const file of readdirSync(`node_modules/pdfjs-dist/${dir}`)) {
            this.emitFile({
              type: "asset",
              fileName: `pdfjs/${dir}/${file}`,
              source: readFileSync(`node_modules/pdfjs-dist/${dir}/${file}`),
            });
          }
        }
        const packages = [
          "react",
          "react-dom",
          "scheduler",
          "vite",
          "pdfjs-dist",
          "lucide-react",
          "dompurify",
          "marked",
        ];
        this.emitFile({
          type: "asset",
          fileName: "THIRD_PARTY_NOTICES.txt",
          source: packages
            .map(
              (name) =>
                `${name}\n${readFileSync(`node_modules/${name}/${name === "vite" ? "LICENSE.md" : "LICENSE"}`, "utf8")}\n`,
            )
            .join("\n"),
        });
      },
    },
  ],
  base: "/static/workbench/",
  build: {
    outDir: "../static/workbench",
    emptyOutDir: true,
    manifest: true,
    rolldownOptions: { input: "src/main.tsx" },
  },
});
