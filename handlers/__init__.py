"""Handler package. Import submodules then register their routers."""
from . import admin, alt, catalog, common, pay, wallet, search, grizzly
from utils.bulk_tg import router as bulk_router


def setup_handlers(dp) -> None:
    for router in (common.router, wallet.router, catalog.router,
                   alt.router, grizzly.router, admin.router, pay.router, search.router,
                   bulk_router):
        dp.include_router(router)
