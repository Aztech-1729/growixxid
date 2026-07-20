"""Handler package. Import submodules then register their routers."""
from . import admin, alt, catalog, common, pay, wallet, search, grizzly


def setup_handlers(dp) -> None:
    for router in (common.router, wallet.router, catalog.router,
                   alt.router, grizzly.router, admin.router, pay.router, search.router):
        dp.include_router(router)
