from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
for pkg in ("markdown", "pygments", "trafilatura"):
    hiddenimports += collect_submodules(pkg)

a = Analysis(
    ["src/assistant/main.py"],
    pathex=["src"],
    hiddenimports=hiddenimports + collect_submodules("playwright"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="assistant",
    console=False,
    upx=False,
)
