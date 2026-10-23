"""PyInstaller entry point that imports boss_tool as a proper package."""
from boss_tool.app import main

if __name__ == "__main__":
    raise SystemExit(main())
