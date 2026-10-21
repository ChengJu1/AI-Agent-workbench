"""Install a pinned official runtime without modifying user/browser profiles."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.platform.native_mcp import MCP_VERSION, RUNTIME

if __name__ == '__main__':
    npm = shutil.which('npm')
    if not npm:
        raise SystemExit('请先安装 Node.js 18 或更新版本。')
    subprocess.run([npm, 'install', '--prefix', str(RUNTIME), '--ignore-scripts', '--no-audit',
                    '--no-fund', '--save-exact', '@playwright/mcp@' + MCP_VERSION], check=True)
    print('官方浏览器组件已准备好。请使用专用浏览器登录，个人 Chrome 配置不会被读取。')
