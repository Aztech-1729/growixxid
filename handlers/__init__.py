"""Handler package. Import submodules then register their routers."""
from . import admin, alt, catalog, common, pay


def setup_handlers(dp) -> None:
    for router in (common.router, catalog.router, alt.router, admin.router, pay.router):
        dp.include_router(router)
