// 配置 Vite 开发和构建工具，并启用 React 插件。
// 前端执行 npm run dev 或 npm run build 时会读取该文件。
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
