import asyncio
import aiohttp
import json

TELEGRAM_BOT_TOKEN = "7653720492:AAGXkXE3WcYW-fF3pDDvTWgrHxfr5Parnvk"

async def get_chat_id():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            print("🔍 Chat ID Lookup Result:")
            print(json.dumps(data, indent=2))

if __name__ == "__main__":
    asyncio.run(get_chat_id())