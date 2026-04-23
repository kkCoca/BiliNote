from fastapi import FastAPI



def create_app(lifespan) -> FastAPI:
    app = FastAPI(title="BiliNote",lifespan=lifespan)

    # Import routers lazily to keep `import app` lightweight.
    from .routers import note, provider, model, config, chat, batch

    app.include_router(note.router, prefix="/api")
    app.include_router(batch.router, prefix="/api")
    app.include_router(provider.router, prefix="/api")
    app.include_router(model.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    return app
