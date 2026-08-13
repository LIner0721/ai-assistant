"""本地构建脚本：python build.py"""
import subprocess
import sys


def main():
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "--clean",
         "--noconfirm", "assistant.spec"])
    print("构建完成：dist/assistant(.exe)")


if __name__ == "__main__":
    main()
