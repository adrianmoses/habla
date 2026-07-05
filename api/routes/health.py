from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    if not request.app.state.ready:
        return JSONResponse(
            status_code=503,
            content={"status": "warming_up", "llm_backend": settings.llama_cpp_url},
        )
    db = getattr(request.app.state, "db", None)
    if db is None or not await db.ping():
        return JSONResponse(
            status_code=503,
            content={
                "status": "db_unreachable",
                "llm_backend": settings.llama_cpp_url,
            },
        )
    return JSONResponse(content={"status": "ok", "llm_backend": settings.llama_cpp_url})
