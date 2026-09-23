# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

from pathlib import Path
ROOT = Path(SPECPATH).resolve().parent

datas = []
hiddenimports = ['studio.worker', 'studio.android', 'studio.pairing', 'studio.popups', 'studio.service', 'pytest']
# pytest 随工程 vendor 分发；不能依赖构建机全局 Python 是否安装它。
for metadata in ('pytest-9.1.1.dist-info', 'pluggy-1.6.0.dist-info', 'iniconfig-2.3.0.dist-info'):
    datas.append((str(ROOT / 'vendor' / metadata), metadata))
hiddenimports += collect_submodules('_pytest')
hiddenimports += collect_submodules('appium')


a = Analysis(
    [str(ROOT / 'launch.py')],
    pathex=[str(ROOT), str(ROOT / 'vendor')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GlassesStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GlassesStudio',
)
