"""
MIA TUI — prompt_toolkit 聊天界面

用法:
    from mia.tui_prompt.app import MiaTuiApp
    app = MiaTuiApp(bus=bus, config=config)
    await app.run()
"""

from mia.tui_prompt.app import MiaTuiApp

__all__ = ["MiaTuiApp"]
