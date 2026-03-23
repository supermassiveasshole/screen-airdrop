from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.render.renderer_cv2 import CV2Renderer

__all__ = ["CV2Renderer"]


def __getattr__(name):
    if name == "CV2Renderer":
        from screen_airdrop.sender.render.renderer_cv2 import CV2Renderer

        return CV2Renderer
    raise AttributeError(name)
