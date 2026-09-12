import json
import httpx
from backend.config import LLM_API_KEY,LLM_MODEL

class GroqProvider:
    def __init__(self,key=LLM_API_KEY):
        self.key=key
        self.state={'status':'UNVERIFIED' if key else 'MISSING KEY','detail':'Structured numerical engines remain authoritative.'}
    async def explain(self,message,context):
        if not self.key:
            return None
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response=await client.post('https://api.groq.com/openai/v1/chat/completions',headers={'Authorization':f'Bearer {self.key}'},json={
                    'model':LLM_MODEL,'temperature':0,'max_tokens':450,'messages':[
                    {'role':'system','content':'You explain outputs from a maritime decision-support prototype. Use only supplied structured facts. Do not invent coordinates, counts, fuel, vessel histories, events, legal conclusions or operational capabilities. Distinguish historical data, model forecasts and simulated collector assets. AIS gaps are not proof of wrongdoing. Be concise and answer the user in at most 120 words.'},
                    {'role':'user','content':json.dumps({'request':message,'verified_context':context},ensure_ascii=False)}]})
            if response.status_code in (401,403):
                self.state.update(status='AUTHENTICATION FAILED',detail='Groq rejected the configured key.')
                return None
            response.raise_for_status(); answer=response.json()['choices'][0]['message']['content']
            self.state.update(status='CONNECTED',detail='Groq explains only supplied engine outputs.')
            return answer
        except httpx.HTTPStatusError as exc:
            self.state.update(status='OFFLINE FALLBACK',detail=f'Groq returned HTTP {exc.response.status_code}; deterministic explanations are active.')
            return None
        except (httpx.HTTPError,ValueError,KeyError,IndexError) as exc:
            self.state.update(status='OFFLINE FALLBACK',detail=f'Groq unavailable ({type(exc).__name__}); deterministic explanations are active.')
            return None
