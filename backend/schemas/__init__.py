from typing import Literal
from pydantic import BaseModel, Field

class RouteRequest(BaseModel):
    origin_id: str
    destination_id: str
    speed_knots: float = Field(default=12, ge=4, le=28)
    reference_fuel_tpd: float = Field(default=24, gt=0, le=500)
    safety_buffer_km: float = Field(default=1.0, ge=0, le=10)

class CleanupRequest(BaseModel):
    hours: float = Field(default=6, ge=1, le=24)
    collectors: int = Field(default=3, ge=1, le=8)

class ReplanRequest(BaseModel):
    mission_id: str
    event: Literal['battery_drop', 'wave_warning', 'new_debris_report']
    collector_id: str | None = None

class CommandRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1500)

class ReplayRequest(BaseModel):
    vessel_id: str | None = Field(default=None, min_length=1, max_length=100)
    speed: float = Field(default=60, ge=1, le=3600)
    limit: int = Field(default=200, ge=1, le=2000)
