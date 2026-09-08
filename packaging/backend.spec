from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas, binaries, hiddenimports = [], [], []
for package in ('windows_capture', 'onnxruntime'):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
a = Analysis([str(root / 'backend/main.py')], pathex=[str(root / 'backend')],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['torch', 'torchvision', 'matplotlib', 'pytest', 'IPython'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='tft-coach-backend',
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='tft-coach-backend')
