import asyncio
from fastapi import WebSocket

class WebSocketManager:
    def __init__(self): self.clients=set()
    async def connect(self,websocket:WebSocket):
        await websocket.accept(); self.clients.add(websocket)
    def disconnect(self,websocket): self.clients.discard(websocket)
    async def broadcast(self,kind,data):
        if not self.clients:return
        clients=list(self.clients)
        results=await asyncio.gather(*(client.send_json({'type':kind,'data':data}) for client in clients),return_exceptions=True)
        for client,result in zip(clients,results):
            if isinstance(result,Exception):self.disconnect(client)

manager=WebSocketManager()
