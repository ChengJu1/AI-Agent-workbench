"""Choose an installed browser binary without reading or reusing personal profiles."""
import os
import shutil
import sys
from pathlib import Path
from app.errors import ServiceError


def installed_channel(channel):
    if sys.platform == 'darwin':
        name = 'Google Chrome' if channel == 'chrome' else 'Microsoft Edge'
        return Path(f'/Applications/{name}.app/Contents/MacOS/{name}').is_file()
    if sys.platform == 'win32':
        suffix = 'Google/Chrome/Application/chrome.exe' if channel == 'chrome' else 'Microsoft/Edge/Application/msedge.exe'
        return any((Path(os.environ[root]) / suffix).is_file() for root in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA') if os.environ.get(root))
    names = ('google-chrome','google-chrome-stable') if channel == 'chrome' else ('microsoft-edge','microsoft-edge-stable')
    return any(shutil.which(name) for name in names)


def browser_choice(directory, preference=None):
    preference = preference or os.getenv('WORKBENCH_BROWSER_CHANNEL','auto')
    if preference not in ('auto','chrome','msedge','chromium'):
        raise ServiceError('WORKBENCH_BROWSER_CHANNEL 仅支持 auto、chrome、msedge、chromium。', 422)
    channel = ('chrome' if installed_channel('chrome') else 'chromium') if preference == 'auto' else preference
    bundled = any(Path(directory).glob('chromium-*'))
    return {'channel':channel,'browser_name':{'chrome':'Google Chrome','msedge':'Microsoft Edge','chromium':'Chromium'}[channel],
            'available':bundled if channel == 'chromium' else bool(installed_channel(channel))}
