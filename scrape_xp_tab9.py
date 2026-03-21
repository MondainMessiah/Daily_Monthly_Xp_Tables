import asyncio
from curl_cffi.requests import AsyncSession

async def test_new_site():
    print("🚀 Testing tibia-statistic.com bypass...")
    url = "https://www.tibia-statistic.com/"
    
    HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        async with AsyncSession(impersonate="chrome120") as session:
            response = await session.get(url, headers=HEADERS, timeout=15)
            print(f"📡 Status Code: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ SUCCESS! Cloudflare let us through! We can build a scraper for this site.")
            elif response.status_code in [403, 429]:
                print(f"❌ FAILED: HTTP {response.status_code}. Cloudflare blocked GitHub's Datacenter IP again.")
            else:
                print(f"⚠️ Unknown response: {response.status_code}")
                
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_new_site())
