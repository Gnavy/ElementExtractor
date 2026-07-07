from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.case1_tasks import router as case1_router
from app.api.case2_tasks import router as case2_router
from app.api.tasks import router as tasks_router
from app.api.v1.tasks import router as v1_tasks_router
from app.database import Base, engine, migrate_sqlite_schema
from app.services.paths import ensure_storage

ensure_storage()
Base.metadata.create_all(bind=engine)
migrate_sqlite_schema()

OPENAPI_TAGS = [
    {
        "name": "v1-tasks",
        "description": "对外统一任务 API（需 API Key，见 X-API-Key 请求头）",
    },
    {"name": "tasks", "description": "内部任务 API（无鉴权，供前端使用）"},
    {"name": "case1", "description": "Case1 内部创建入口"},
    {"name": "case2", "description": "Case2 内部创建入口"},
]

app = FastAPI(
    title="业务审查任务开放 API",
    version="1.0.0",
    description=(
        "统一任务接口，支持 **classification**（材料分类）、**extraction**（要素抽取）、"
        "**due_diligence**（债权尽调填报）、**template_fill**（模板驱动填报）。"
        "对外集成请使用 `/api/v1/*` 并携带 API Key。"
    ),
    openapi_tags=OPENAPI_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_tasks_router)
app.include_router(tasks_router)
app.include_router(case1_router)
app.include_router(case2_router)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
    )
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "在 `.env` 中配置 `API_KEYS`；亦支持 `Authorization: Bearer <key>`",
        }
    }
    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
