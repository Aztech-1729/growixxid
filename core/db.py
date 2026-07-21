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
    now = datetime.datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - datetime.timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    
    pipeline = [
        {"$match": {"status": "completed"}},
        {"$group": {
            "_id": None,
            "today": {"$sum": {"$cond": [{"$gte": ["$created_at", today_start]}, "$price_inr", 0]}},
            "week": {"$sum": {"$cond": [{"$gte": ["$created_at", week_start]}, "$price_inr", 0]}},
            "month": {"$sum": {"$cond": [{"$gte": ["$created_at", month_start]}, "$price_inr", 0]}},
        }}
    ]
    cursor = orders.aggregate(pipeline)
    result = await cursor.to_list(length=1)
    
    # most popular services
    pop_pipeline = [
        {"$match": {"status": "completed"}},
        {"$group": {"_id": "$service", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 3}
    ]
    pop_cursor = orders.aggregate(pop_pipeline)
    pop_result = await pop_cursor.to_list(length=3)
    
    return {
        "revenue": result[0] if result else {"today": 0, "week": 0, "month": 0},
        "popular": pop_result
    }

async def get_recent_failed_orders(limit: int = 5):
    cur = orders.find({"status": {"$in": ["refunded", "failed"]}}).sort("created_at", -1).limit(limit)
    return await cur.to_list(length=limit)
