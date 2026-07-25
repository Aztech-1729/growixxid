"""MongoDB layer (Motor, async) with indexes for fast lookups.

Collections:
  users        -> one doc per Telegram user
  orders       -> one doc per purchased number/OTP
  settings     -> key/value config
  transactions -> wallet / balance movements
"""
import datetime
from datetime import timezone

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import config

_client = AsyncIOMotorClient(config.MONGO_URI)
db = _client[config.MONGO_DB]

users: "object" = db["users"]
orders: "object" = db["orders"]
settings: "object" = db["settings"]
transactions: "object" = db["transactions"]


async def init_indexes() -> None:
    """Create indexes once at startup for query speed."""
    await users.create_index("user_id", unique=True)
    await orders.create_index("order_ref", unique=True)
    await orders.create_index([("user_id", 1), ("created_at", -1)])
    await orders.create_index("status")
    await transactions.create_index([("user_id", 1), ("created_at", -1)])
    await settings.create_index("key", unique=True)


async def register_user(u) -> None:
    await users.update_one(
        {"user_id": u.id},
        {"$setOnInsert": {
            "user_id": u.id,
            "username": u.username,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "joined_at": datetime.datetime.now(timezone.utc),
            "wallet": 0.0,
            "banned": False,
        }},
        upsert=True,
    )


async def get_user(user_id: int):
    return await users.find_one({"user_id": user_id})


async def add_order(**kw) -> None:
    kw.setdefault("created_at", datetime.datetime.now(timezone.utc))
    kw.setdefault("updated_at", datetime.datetime.now(timezone.utc))
    kw.setdefault("status", "pending")
    await orders.insert_one(kw)


async def update_order(ref: str, **fields) -> None:
    fields["updated_at"] = datetime.datetime.now(timezone.utc)
    await orders.update_one({"order_ref": ref}, {"$set": fields})


async def get_order(ref: str):
    return await orders.find_one({"order_ref": ref})


async def get_user_orders(user_id: int, skip: int = 0, limit: int = 10):
    cur = orders.find({"user_id": user_id}).sort("created_at", -1).skip(skip).limit(limit)
    return await cur.to_list(length=limit)

async def count_user_orders(user_id: int) -> int:
    return await orders.count_documents({"user_id": user_id})


async def count_users() -> int:
    return await users.count_documents({})


async def count_orders() -> int:
    return await orders.count_documents({})


async def get_all_users():
    return await users.find({}).to_list(length=100000)

async def get_all_users_paginated(skip: int = 0, limit: int = 10):
    cur = users.find({}).sort("joined_at", -1).skip(skip).limit(limit)
    return await cur.to_list(length=limit)

async def get_all_orders_paginated(skip: int = 0, limit: int = 10):
    cur = orders.find({}).sort("created_at", -1).skip(skip).limit(limit)
    return await cur.to_list(length=limit)


# ---- wallet ----
async def get_wallet(user_id: int) -> float:
    u = await users.find_one({"user_id": user_id})
    return float(u.get("wallet", 0.0)) if u else 0.0


async def credit_wallet(user_id: int, amount: float, note: str = "") -> None:
    # upsert=True so a payment that arrives before /start still credits correctly
    await users.update_one(
        {"user_id": user_id},
        {"$inc": {"wallet": float(amount)},
         "$setOnInsert": {"joined_at": datetime.datetime.now(timezone.utc), "banned": False}},
        upsert=True)
    await transactions.insert_one({
        "user_id": user_id, "type": "credit", "amount": float(amount),
        "note": note, "created_at": datetime.datetime.now(timezone.utc)})


async def deduct_wallet(user_id: int, amount: float, note: str = "") -> bool:
    u = await users.find_one({"user_id": user_id})
    if not u or float(u.get("wallet", 0.0)) < float(amount):
        return False
    await users.update_one({"user_id": user_id}, {"$inc": {"wallet": -float(amount)}})
    await transactions.insert_one({
        "user_id": user_id, "type": "debit", "amount": float(amount),
        "note": note, "created_at": datetime.datetime.now(timezone.utc)})
    return True


async def set_currency_pref(user_id: int, currency: str) -> None:
    await users.update_one(
        {"user_id": user_id},
        {"$set": {"currency_pref": currency}},
        upsert=True)


async def get_currency_pref(user_id: int) -> str:
    u = await users.find_one({"user_id": user_id})
    return u.get("currency_pref", "INR") if u else "INR"


# ---- settings ----
async def get_setting(key: str, default=None):
    doc = await settings.find_one({"key": key})
    if doc:
        return doc.get("value")
    return default

async def set_setting(key: str, value) -> None:
    await settings.update_one(
        {"key": key},
        {"$set": {"value": value}},
        upsert=True
    )


# ---- user management ----
async def toggle_ban_user(user_id: int) -> bool:
    u = await users.find_one({"user_id": user_id})
    if not u:
        return False
    new_status = not u.get("banned", False)
    await users.update_one({"user_id": user_id}, {"$set": {"banned": new_status}})
    return new_status


# ---- analytics ----
async def get_sales_report() -> dict:
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(IST)
    today_start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_ist = today_start_ist - timedelta(days=today_start_ist.weekday())
    month_start_ist = today_start_ist.replace(day=1)

    today_start = today_start_ist.astimezone(timezone.utc)
    week_start = week_start_ist.astimezone(timezone.utc)
    month_start = month_start_ist.astimezone(timezone.utc)
    
    pipeline = [
        {"$group": {
            "_id": None,
            "rev_today": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", today_start]}, {"$eq": ["$status", "completed"]}]}, "$price_inr", 0]}},
            "rev_week": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", week_start]}, {"$eq": ["$status", "completed"]}]}, "$price_inr", 0]}},
            "rev_month": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", month_start]}, {"$eq": ["$status", "completed"]}]}, "$price_inr", 0]}},
            "rev_all": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, "$price_inr", 0]}},
            
            "orders_today_comp": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", today_start]}, {"$eq": ["$status", "completed"]}]}, 1, 0]}},
            "orders_week_comp": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", week_start]}, {"$eq": ["$status", "completed"]}]}, 1, 0]}},
            "orders_month_comp": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", month_start]}, {"$eq": ["$status", "completed"]}]}, 1, 0]}},
            "orders_all_comp": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
            
            "orders_today_fail": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", today_start]}, {"$in": ["$status", ["failed", "refunded", "cancelled"]]}]}, 1, 0]}},
            "orders_week_fail": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", week_start]}, {"$in": ["$status", ["failed", "refunded", "cancelled"]]}]}, 1, 0]}},
            "orders_month_fail": {"$sum": {"$cond": [{"$and": [{"$gte": ["$created_at", month_start]}, {"$in": ["$status", ["failed", "refunded", "cancelled"]]}]}, 1, 0]}},
            "orders_all_fail": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "refunded", "cancelled"]]}, 1, 0]}},
        }}
    ]
    cursor = orders.aggregate(pipeline)
    result = await cursor.to_list(length=1)
    
    # most popular services (top 5)
    pop_pipeline = [
        {"$match": {"status": "completed"}},
        {"$group": {"_id": "$service", "count": {"$sum": 1}, "revenue": {"$sum": "$price_inr"}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    pop_cursor = orders.aggregate(pop_pipeline)
    pop_result = await pop_cursor.to_list(length=5)
    
    if not result:
        res = {
            "rev_today": 0, "rev_week": 0, "rev_month": 0, "rev_all": 0,
            "orders_today_comp": 0, "orders_week_comp": 0, "orders_month_comp": 0, "orders_all_comp": 0,
            "orders_today_fail": 0, "orders_week_fail": 0, "orders_month_fail": 0, "orders_all_fail": 0,
        }
    else:
        res = result[0]
        
    return {
        "stats": res,
        "popular": pop_result
    }

async def get_user_stats() -> dict:
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(IST)
    today_start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_ist = today_start_ist - timedelta(days=today_start_ist.weekday())
    month_start_ist = today_start_ist.replace(day=1)

    today_start = today_start_ist.astimezone(timezone.utc)
    week_start = week_start_ist.astimezone(timezone.utc)
    month_start = month_start_ist.astimezone(timezone.utc)
    
    pipeline = [
        {"$group": {
            "_id": None,
            "users_today": {"$sum": {"$cond": [{"$gte": ["$joined_at", today_start]}, 1, 0]}},
            "users_week": {"$sum": {"$cond": [{"$gte": ["$joined_at", week_start]}, 1, 0]}},
            "users_month": {"$sum": {"$cond": [{"$gte": ["$joined_at", month_start]}, 1, 0]}},
            "users_all": {"$sum": 1},
        }}
    ]
    cursor = users.aggregate(pipeline)
    result = await cursor.to_list(length=1)
    if not result:
        return {"users_today": 0, "users_week": 0, "users_month": 0, "users_all": 0}
    return result[0]

async def get_recent_failed_orders(limit: int = 5):
    cur = orders.find({"status": {"$in": ["refunded", "failed"]}}).sort("created_at", -1).limit(limit)
    return await cur.to_list(length=limit)

async def count_failed_orders() -> int:
    return await orders.count_documents({"status": {"$in": ["refunded", "failed"]}})

async def get_failed_orders_paginated(skip: int = 0, limit: int = 10):
    cur = orders.find({"status": {"$in": ["refunded", "failed"]}}).sort("created_at", -1).skip(skip).limit(limit)
    return await cur.to_list(length=limit)
