"""
API usage tracking — logs Claude API calls to the api_usage table.
"""
from db.database import execute_insert

# Pricing per million tokens (as of 2026)
_COST_PER_MTK_IN = {
    "claude-haiku-4-5-20251001": 0.80,
    "claude-sonnet-4-6-20250116": 3.00,
}
_COST_PER_MTK_OUT = {
    "claude-haiku-4-5-20251001": 4.00,
    "claude-sonnet-4-6-20250116": 15.00,
}


def calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    rate_in = _COST_PER_MTK_IN.get(model, 3.00) / 1_000_000
    rate_out = _COST_PER_MTK_OUT.get(model, 15.00) / 1_000_000
    return round(tokens_in * rate_in + tokens_out * rate_out, 6)


async def log_usage(model: str, tokens_in: int, tokens_out: int, trigger: str) -> float:
    """Log an API call and return the cost in USD."""
    cost = calc_cost(model, tokens_in, tokens_out)
    await execute_insert(
        "INSERT INTO api_usage (model, tokens_in, tokens_out, cost_usd, trigger) VALUES (?, ?, ?, ?, ?)",
        (model, tokens_in, tokens_out, cost, trigger),
    )
    return cost
