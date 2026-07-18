"""Macro metrics snapshot (PRD R8): GDP proxy, CPI, unemployment, money supply,
index, Gini, sentiment. Computed engine-side every tick from the store — never by
an LLM — so emergent phenomena have an objective metric signature (PRD Goal 2).
"""
from __future__ import annotations

from engine.core import Economy
from engine.store import load_json


class Metrics:
    def __init__(self, economy: Economy, *, semantics_version: int = 2):
        self.e = economy
        self.store = economy.store
        self.semantics_version = semantics_version

    def snapshot(self, tick: int) -> dict:
        out = {}
        out["gdp_proxy"] = self._gdp_proxy(tick)
        if self.semantics_version >= 3:
            out["labor_income"] = self._labor_income(tick)
            out["gdp_proxy_30d"] = self._gdp_proxy_30d(tick)
        out["cpi"] = self._cpi()
        if self.semantics_version >= 3:
            if tick >= 30:
                out["inflation_30d"] = self._inflation_30d(tick, out["cpi"])
            if tick >= 365:
                out["cpi_yoy"] = self._cpi_yoy(tick, out["cpi"])
        else:
            out["cpi_yoy"] = self._cpi_yoy(tick, out["cpi"])
        out["unemployment"] = self._unemployment()
        out["money_supply"] = self.e.ledger.total_deposits_cents() / 100.0
        out["gini"] = self._gini()
        out["sentiment"] = self._sentiment()
        idx = self.e.exchange.compute_index(tick)
        if idx is not None:
            out["index"] = idx
            out["index_change_10"] = self._index_change(tick, idx, 10)
        out["policy_rate"] = self.e.policy_rate_bps()
        for bank in self.store.query("SELECT id FROM banks"):
            bid = int(bank["id"])
            out[f"bank_deposits:{bid}"] = self.e.bank.deposits(bid) / 100.0
            out[f"bank_reserve_ratio:{bid}"] = self.e.bank.reserve_ratio(bid)
        # Fiscal + health economy (P1 R12/R17).
        if self.e.gov.enabled:
            out["gov_balance"] = self.e.gov.treasury_balance() / 100.0
            out["tax_rate_bps"] = self.e.gov.tax_rate_bps()
            out["unemployment_benefit_cents"] = self.e.gov.benefit_cents()
        out["insured_count"] = float(self.store.scalar(
            "SELECT COUNT(*) FROM insurance_policies WHERE status='active'", default=0))
        out["epidemic_multiplier"] = self.store.metric_latest("epidemic_multiplier", 1.0)
        if self.semantics_version >= 4:
            out["hhi"] = self._market_hhi(tick)
            out["innovation_rate_30d"] = float(self.store.scalar(
                "SELECT COUNT(*) FROM ip_assets WHERE registered_tick BETWEEN ? AND ?",
                (max(0, tick - 29), tick), default=0))
            out["litigation_burden"] = float(self.store.scalar(
                "SELECT COUNT(*) FROM legal_matters WHERE status NOT IN ('settled','decided','dismissed')",
                default=0)) / max(1.0, float(self.store.scalar(
                    "SELECT COUNT(*) FROM firms WHERE status<>'bankrupt'", default=0)))
            out["lobbying_spend_30d"] = float(self.store.scalar(
                "SELECT COALESCE(SUM(amount_cents),0) FROM lobbying_activities WHERE tick BETWEEN ? AND ?",
                (max(0, tick - 29), tick), default=0)) / 100.0
            out["narrative_distortion"] = float(self.store.scalar(
                "SELECT COALESCE(AVG(distortion),0) FROM information_items WHERE tick BETWEEN ? AND ?",
                (max(0, tick - 29), tick), default=0) or 0)
            out["firm_entries"] = float(self.store.scalar(
                "SELECT COUNT(*) FROM firms WHERE founded_tick=?", (tick,), default=0))
            out["firm_exits"] = float(self.store.scalar(
                "SELECT COUNT(*) FROM events WHERE tick=? AND kind IN ('bankruptcy','merger_closed')",
                (tick,), default=0))
        if self.semantics_version >= 5:
            out["fx_volume"] = float(self.store.scalar(
                "SELECT COALESCE(SUM(base_qty),0) FROM fx_trades WHERE tick=?", (tick,), default=0))
        for name, value in out.items():
            if self.semantics_version >= 2:
                # FINALIZE may be safely replayed after an interrupted boundary.
                self.store.execute(
                    "DELETE FROM metrics WHERE tick=? AND name=?", (tick, name))
            self.store.record_metric(tick, name, float(value))
        return out

    def _market_hhi(self, tick: int) -> float:
        rows = self.store.query(
            "SELECT CAST(json_extract(payload_json,'$.firm_id') AS INTEGER) AS firm_id,"
            "COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) AS revenue "
            "FROM events WHERE kind='goods_sale' AND tick BETWEEN ? AND ? GROUP BY firm_id",
            (max(0, tick - 29), tick))
        total = sum(max(0, float(row["revenue"] or 0)) for row in rows)
        if total <= 0:
            return 0.0
        return sum((float(row["revenue"] or 0) / total * 100.0) ** 2 for row in rows)

    def _gdp_proxy(self, tick: int) -> float:
        """Final-goods sales for one tick; legacy v1/v2 also included wages."""
        v = self.store.scalar(
            "SELECT COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) FROM events "
            "WHERE tick=? AND kind='goods_sale'", (tick,), default=0)
        if self.semantics_version >= 3:
            return float(v) / 100.0
        w = self.store.scalar(
            "SELECT COALESCE(SUM(json_extract(payload_json,'$.wage_cents')),0) FROM events "
            "WHERE tick=? AND kind='wage_paid'", (tick,), default=0)
        return (float(v) + float(w)) / 100.0

    def _labor_income(self, tick: int) -> float:
        wages = self.store.scalar(
            "SELECT COALESCE(SUM(json_extract(payload_json,'$.wage_cents')),0) FROM events "
            "WHERE tick=? AND kind='wage_paid'", (tick,), default=0)
        return float(wages) / 100.0

    def _gdp_proxy_30d(self, tick: int) -> float:
        value = self.store.scalar(
            "SELECT COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) FROM events "
            "WHERE kind='goods_sale' AND tick BETWEEN ? AND ?",
            (max(1, tick - 29), tick), default=0)
        return float(value) / 100.0

    def _cpi(self) -> float:
        """Fixed genesis-goods basket (base 100), immune to survivor bias."""
        if self.semantics_version >= 2:
            firms = self.store.query(
                "SELECT product_json FROM firms WHERE founded_tick=0 "
                "AND sector NOT IN ('health','insurance') ORDER BY id")
        else:
            firms = self.store.query(
                "SELECT product_json FROM firms "
                "WHERE status IN ('private','listed')")
        prices = []
        for f in firms:
            prod = load_json(f["product_json"], {}) or {}
            p = prod.get("unit_price_cents")
            if p:
                prices.append(int(p))
        if not prices:
            return 100.0
        avg = sum(prices) / len(prices)
        base = self.store.scalar(
            "SELECT value FROM metrics WHERE name='cpi_base' ORDER BY tick LIMIT 1")
        if base is None:
            self.store.record_metric(0, "cpi_base", avg)
            base = avg
        return 100.0 * avg / float(base)

    def _inflation_30d(self, tick: int, cpi_now: float) -> float:
        prev = self.store.metric_at_or_before("cpi", tick - 30, default=0.0)
        return cpi_now / prev - 1.0 if prev > 0 else 0.0

    def _cpi_yoy(self, tick: int, cpi_now: float) -> float:
        if self.semantics_version >= 3:
            if tick < 365:
                raise ValueError("cpi_yoy requires 365 completed ticks")
            prev = self.store.metric_at_or_before("cpi", tick - 365, default=0.0)
            return cpi_now / prev - 1.0 if prev > 0 else 0.0
        prev = self.store.metric_at_or_before("cpi", max(0, tick - 365), default=0.0)
        if prev <= 0:
            prev = self.store.metric_at_or_before("cpi", 0, default=100.0) or 100.0
            span = max(1, tick)
            return ((cpi_now / prev) ** (365.0 / span) - 1.0) if cpi_now > 0 else 0.0
        return cpi_now / prev - 1.0

    def _unemployment(self) -> float:
        labor_force = self.store.scalar(
            "SELECT COUNT(*) FROM agents WHERE alive=1 AND retired=0 AND kind='citizen' "
            "AND age BETWEEN 18 AND 64", default=0)
        if not labor_force:
            return 0.0
        if self.semantics_version >= 7:
            working = self.store.scalar(
                "SELECT COUNT(*) FROM agents a WHERE a.alive=1 AND a.retired=0 "
                "AND a.kind='citizen' AND a.age BETWEEN 18 AND 64 AND ("
                "EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id AND e.status='active') "
                "OR EXISTS (SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id "
                "AND f.status<>'bankrupt'))", default=0)
        else:
            employed = self.store.scalar(
                "SELECT COUNT(DISTINCT e.agent_id) FROM employments e "
                "JOIN agents a ON a.id=e.agent_id WHERE e.status='active' "
                "AND a.alive=1 AND a.retired=0 AND a.kind='citizen'", default=0)
            founders = self.store.scalar(
                "SELECT COUNT(DISTINCT f.founder_agent_id) FROM firms f "
                "JOIN agents a ON a.id=f.founder_agent_id WHERE f.status<>'bankrupt' "
                "AND a.alive=1 AND a.retired=0 AND a.kind='citizen'", default=0)
            working = min(int(labor_force), int(employed) + int(founders))
        return max(0.0, 1.0 - working / int(labor_force))

    def _gini(self) -> float:
        rows = self.store.query(
            "SELECT COALESCE(SUM(a.balance_cents),0) AS w FROM agents ag "
            "LEFT JOIN accounts a ON a.owner_type='agent' AND a.owner_id=ag.id "
            "WHERE ag.alive=1 AND ag.kind='citizen' GROUP BY ag.id")
        wealth = sorted(max(0, int(r["w"])) for r in rows)
        n = len(wealth)
        total = sum(wealth)
        if n == 0 or total == 0:
            return 0.0
        cum = 0.0
        weighted = 0.0
        for i, w in enumerate(wealth, start=1):
            weighted += i * w
        return (2.0 * weighted) / (n * total) - (n + 1.0) / n

    def _sentiment(self) -> float:
        v = self.store.scalar(
            "SELECT AVG(value) FROM beliefs WHERE key='sentiment'", default=0.0)
        return float(v or 0.0)

    def _index_change(self, tick: int, idx_now: float, window: int) -> float:
        prev = self.store.metric_at_or_before("index", max(0, tick - window), default=0.0)
        if prev <= 0:
            return 0.0
        return idx_now / prev - 1.0
