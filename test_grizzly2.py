import asyncio
import httpx
from core.config import config

async def main():
    api_key = config.GRIZZLY_API_KEY
    url = f"https://api.grizzlysms.com/api/v2/getServices?api_key={api_key}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url)
            print(r.text[:500])
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
