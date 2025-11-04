from __future__ import annotations
from .schema import PlanComposite, TouPlan

def validate_plan(plan: PlanComposite) -> None:
    # basic overlap sanity for TOU
    if isinstance(plan.energy, TouPlan):
        # ensure at least one class exists
        if not plan.energy.energy_classes:
            raise ValueError("TOU plan must define energy_classes")
        # simple window syntax check
        for ec in plan.energy.energy_classes:
            for w in (ec.windows or []):
                if w.start == w.end:
                    raise ValueError(f"Window '{w.name}' start==end not allowed")
