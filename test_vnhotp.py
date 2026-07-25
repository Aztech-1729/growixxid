import asyncio
from core.config import config
from services.vnhotp import vnhotp
from utils.session_maker import AutoSessionManager

async def test():
    print("Fetching Indian TG price...")
    try:
        price = await vnhotp.tg_country_info("IN")
        print(f"Price: {price}")
    except Exception as e:
        print(f"Failed to get price: {e}")
        return

    print("Placing order for IN...")
    try:
        order = await vnhotp.tg_place_order("IN")
        print(f"Order: {order}")
    except Exception as e:
        print(f"Failed to place order: {e}")
        return

    number = order["number"]
    pwd = order.get("password")
    print(f"Number: {number}, Password: {pwd}")
    
    manager = AutoSessionManager(number)
    print("Connecting and sending code request...")
    try:
        phone_code_hash = await manager.connect_and_send_code()
        print(f"Code hash: {phone_code_hash}")
    except Exception as e:
        print(f"Failed to connect: {e}")
        manager.cleanup()
        return

    print("Waiting for OTP from VNHOTP API (max 5 mins)...")
    code = None
    for i in range(60):
        try:
            res = await vnhotp.tg_get_code(number)
            if res:
                if isinstance(res, dict) and "code" in res:
                    code = res["code"]
                elif isinstance(res, str):
                    code = res
                else:
                    code = str(res)
                print(f"OTP received: {code}")
                break
        except Exception as e:
            pass
        await asyncio.sleep(5)

    if not code:
        print("Timeout waiting for OTP.")
        manager.cleanup()
        return

    print("Signing in...")
    try:
        session_file = await manager.sign_in_and_get_file(code, password=pwd)
        print(f"Session created successfully: {session_file}")
    except Exception as e:
        print(f"Failed to sign in: {e}")
    finally:
        manager.cleanup()

if __name__ == "__main__":
    asyncio.run(test())
