from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from dataclasses import dataclass

CurrencyCents = float

class DailySupply(BaseModel):
    cents_per_day: CurrencyCents

class TimeWindow(BaseModel):
    name: str
    start: str  # "HH:MM"
    end: str
    days: list[int]            # 0 = Mon ... 6 = Sun
    months: list[int] | None = None

class BlockStep(BaseModel):
    upto_kwh: float | None
    cents_per_kwh: CurrencyCents

class EnergyClass(BaseModel):
    name: str  # "anytime" | "peak" | "shoulder" | "offpeak" | "controlled_load"
    windows: list[TimeWindow] | None = None
    blocks: list[BlockStep] | None = None

class PlanBase(BaseModel):
    name: str
    timezone: str = "Australia/Brisbane"
    daily_supply: DailySupply

class FlatPlan(PlanBase):
    kind: Literal["flat"] = "flat"
    anytime_rate_cents_per_kwh: CurrencyCents
    blocks: list[BlockStep] | None = None

class TouPlan(PlanBase):
    kind: Literal["tou"] = "tou"
    energy_classes: list[EnergyClass]

class PlanComposite(BaseModel):
    energy: FlatPlan | TouPlan
