import asyncio
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from services.grizzly_api import grizzly

async def main():
    try:
        print("\n--- Prices ---")
        p = await grizzly._req("getPrices", service="tg", country="0")
        print(p[:1000])
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
