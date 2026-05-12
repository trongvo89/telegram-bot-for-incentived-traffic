from app.handlers.commands import router as commands_router
from app.handlers.errors import register_error_handler
from app.handlers.photo import router as photo_router

__all__ = ["commands_router", "photo_router", "register_error_handler"]
