// 创建 React 应用入口，并加载主组件和全局样式。
// 浏览器打开页面后会从这里开始渲染 App。
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./workbench.css";
import "./theme.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
