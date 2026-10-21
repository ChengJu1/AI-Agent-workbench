// Keeps one broken dialog from blanking the whole workbench.
import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; onReset?: () => void };

export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("界面渲染失败", error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <div className="renderError" role="alert">
      <strong>这个面板出错了</strong>
      <p>其他功能不受影响。刷新页面通常能恢复；如果反复出现，请把这段信息发给维护者：{this.state.error.message}</p>
      <button type="button" onClick={() => { this.setState({ error: null }); this.props.onReset?.(); }}>关闭</button>
    </div>;
  }
}
