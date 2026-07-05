from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from travel_agent.api.routes import router as api_router
from travel_agent.core.config import get_settings

settings = get_settings()
app = FastAPI(title='Travel Agent API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):(5173|5174|3000)",
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(api_router)


@app.get('/health')
def health_check() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/api/meta')
def meta() -> dict[str, object]:
    return {
        'name': 'Travel Agent API',
        'version': '1.0.0',
        'features': [
            'multi_turn',
            'history',
            'intent_classification',
            'scenario_classification',
            'route_comparison',
            'preference_memory',
        ],
    }
