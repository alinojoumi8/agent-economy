"""Deterministic synthetic persona generation; see ``ATTRIBUTION.md``.

This clean implementation is inspired by LLM-Economist's published
sample-then-enrich approach (Karten et al., 2025). Its occupation weights, age
bands, income medians, and wealth formula are hand-authored synthetic heuristics,
not Census or other microdata and not an empirical population calibration.
Everything is drawn from a passed-in seeded PRNG so a run's fictional population
is reproducible. No LLM is required for the base draw; the runtime may optionally
enrich a persona with one LLM call for arrivals. No upstream source code is
included in this module.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

# Synthetic occupation heuristic:
# (weight, median annual income $, min age, max age).
OCCUPATIONS = [
    ("teacher",        0.10, 55_000, 24, 64),
    ("nurse",          0.09, 78_000, 23, 63),
    ("engineer",       0.09, 105_000, 24, 64),
    ("lawyer",         0.03, 130_000, 27, 68),
    ("economist",      0.02, 115_000, 28, 66),
    ("retail_worker",  0.11, 34_000, 18, 66),
    ("gig_worker",     0.08, 32_000, 19, 60),
    ("accountant",     0.05, 79_000, 24, 64),
    ("software_dev",   0.07, 120_000, 22, 62),
    ("construction",   0.06, 52_000, 19, 63),
    ("doctor",         0.02, 220_000, 30, 68),
    ("small_business", 0.05, 68_000, 26, 70),
    ("journalist",     0.02, 58_000, 24, 64),
    ("retiree",        0.08, 28_000, 65, 92),
    ("student",        0.06, 14_000, 18, 27),
    ("civil_servant",  0.05, 62_000, 24, 64),
]

FIRST_NAMES = ("Ada Ben Carmen Devi Ezra Fiona Gus Hana Iris Jamal Kira Leo Mara Nate "
               "Omar Priya Quinn Rosa Sam Tara Uma Vic Wren Xu Yara Zane Amir Bea Cole "
               "Dara Enzo Faye Gita Hugo Ivy Jonas Kai Lena Milo Nadia Otis Pia Rhea "
               "Silas Thea Ugo Vera Wade Ximena Yusuf Zoe").split()
LAST_NAMES = ("Nguyen Patel Garcia Cohen Okafor Ahmed Rossi Kim Silva Haddad Novak Tan "
              "Diaz Ford Ivanov Mensah Reyes Bauer Costa Adeyemi Larsen Popov Farah "
              "Bianchi Sato Weber Khan Moreau Vargas Holm").split()

TRAITS = ("cautious optimistic frugal impulsive analytical gregarious skeptical trusting "
          "ambitious risk-averse contrarian herd-following stoic anxious").split()
OUTLET_NAMES = ("The Ledger", "Commons Dispatch")


@dataclass
class Persona:
    name: str
    age: int
    occupation: str
    income_cents: int          # annual
    wealth_cents: int          # starting liquid savings
    personality: dict
    risk_tolerance: float
    political_lean: float
    media_diet: list[int]
    dependents: int = 0
    kind: str = "citizen"
    role: Optional[str] = None
    extra: dict = field(default_factory=dict)


def _weighted_choice(prng: random.Random, items, weight_index: int = 1):
    total = sum(i[weight_index] for i in items)
    r = prng.random() * total
    upto = 0.0
    for it in items:
        upto += it[weight_index]
        if r <= upto:
            return it
    return items[-1]


def sample_persona(prng: random.Random, n_outlets: int = 2, occupation: Optional[str] = None) -> Persona:
    if occupation:
        occ = next((o for o in OCCUPATIONS if o[0] == occupation), OCCUPATIONS[0])
    else:
        occ = _weighted_choice(prng, OCCUPATIONS)
    name = occ[0]
    median_income, amin, amax = occ[2], occ[3], occ[4]
    age = prng.randint(amin, amax)

    # Lognormal-ish income around the occupation median.
    income = int(median_income * (0.55 + prng.lognormvariate(0.0, 0.35)))
    income = max(9_000, income)
    # Wealth correlates with age and income (older + richer accumulate more).
    age_factor = max(0.1, (age - 20) / 30.0)
    wealth_multiple = prng.lognormvariate(-0.4, 0.7) * (0.3 + age_factor)
    wealth = int(income * wealth_multiple)
    wealth = max(2_000, wealth)

    personality = {t: round(prng.random(), 2) for t in prng.sample(TRAITS, 3)}
    risk = round(min(1.0, max(0.0, prng.gauss(0.5, 0.2))), 2)
    lean = round(min(1.0, max(-1.0, prng.gauss(0.0, 0.5))), 2)
    diet = sorted(prng.sample(range(1, n_outlets + 1), k=min(n_outlets, 1 + (prng.random() < 0.5))))

    full_name = f"{prng.choice(FIRST_NAMES)} {prng.choice(LAST_NAMES)}"
    dependents = prng.choice([0, 0, 0, 1, 1, 2]) if 25 <= age <= 50 else 0
    return Persona(
        name=full_name, age=age, occupation=name,
        income_cents=income * 100, wealth_cents=wealth * 100,
        personality=personality, risk_tolerance=risk, political_lean=lean,
        media_diet=diet, dependents=dependents)


def sample_population(prng: random.Random, size: int, n_outlets: int = 2) -> list[Persona]:
    return [sample_persona(prng, n_outlets) for _ in range(size)]
