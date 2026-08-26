from app.api.auth import router as auth_router
from app.api.cases import router as cases_router
from app.api.customers import router as customers_router
from app.api.dashboard import router as dashboard_router
from app.api.disputes import router as disputes_router
from app.api.payments import router as payments_router
from app.api.settlements import router as settlements_router
from app.api.webhooks import router as webhooks_router

__all__ = [
    "auth_router",
    "cases_router",
    "customers_router",
    "dashboard_router",
    "disputes_router",
    "payments_router",
    "settlements_router",
    "webhooks_router",
]
