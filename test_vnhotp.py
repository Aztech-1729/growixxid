import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from services.vnhotp import vnhotp

async def main():
    try:
        data = await vnhotp.tg_place_order("1") # USA?
        print(data)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
