"""Single assessment access boundary, independent of discovery and payment providers.

Charging is deliberately disabled. Future purchases/allowances/promo grants must
be resolved here, before returning question content or accepting any answer write.
ADMIN_IDS identifies brand publishers only; it is not a teacher permission gate.
"""

import config


def access_details(test, user_id):
    return {"allowed": True, "reason": "free_launch", "charging_enabled": False,
            "standard_price_uzs": test.get("price_uzs", 5000), "currency": "UZS",
            "brand_publisher": test["created_by"] in config.ADMIN_IDS}


async def require_access(db, test, user_id):
    from services.platform_service import PlatformError
    if not test:
        raise PlatformError("Test topilmadi.", 404)
    decision = access_details(test, user_id)
    if not decision["allowed"]:
        raise PlatformError("Ushbu testga kirish huquqi kerak.", 403)
    return decision
