import httpx
from backend.config import GFW_API_ACCESS_TOKEN

class GlobalFishingWatchProvider:
    """Authenticated server-side adapter. Historical retrieval is acquired in scripts."""
    def __init__(self,key=GFW_API_ACCESS_TOKEN):
        self.key=key
        self.state={'status':'UNVERIFIED' if key else 'MISSING KEY','detail':'Cached historical events are used when available.','last_refresh':None}
    async def search(self,query,limit=5):
        if not self.key:
            self.state.update(status='MISSING KEY',detail='GFW_API_ACCESS_TOKEN is not configured.')
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response=await client.get('https://gateway.api.globalfishingwatch.org/v3/vessels/search',
                    params={'query':query,'datasets[0]':'public-global-vessel-identity:latest','limit':limit},
                    headers={'Authorization':f'Bearer {self.key}'})
            if response.status_code in (401,403):
                self.state.update(status='AUTHENTICATION FAILED',detail=f'GFW returned HTTP {response.status_code}. A valid authorized access token is required.')
                return []
            response.raise_for_status()
            self.state.update(status='API CONNECTED',detail='Authenticated vessel identity endpoint verified.')
            return response.json().get('entries',[])
        except (httpx.HTTPError,ValueError):
            self.state.update(status='OFFLINE CACHE',detail='GFW request failed; available downloaded events remain accessible.')
            return []
