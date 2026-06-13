"""
Calculator MCP Server v2
Fix: R-squared division-by-zero protection in OLS tool.
All arithmetic must go through these tools — NEVER let the LLM calculate.
"""

import json
import math
from fastmcp import FastMCP

mcp = FastMCP("treasury-calculator")


def _parse_values(values: list) -> list[float]:
    import re
    result = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, (int, float)) and not math.isnan(float(v)):
            result.append(float(v))
        elif isinstance(v, str):
            cleaned = re.sub(r"[,$%\s]", "", v.strip())
            cleaned = re.sub(r"\d+/$", "", cleaned)
            cleaned = cleaned.replace("(", "-").replace(")", "")
            try:
                f = float(cleaned)
                if not math.isnan(f):
                    result.append(f)
            except ValueError:
                pass
    return result


@mcp.tool()
def calculate_sum(values: list, round_decimals: int = 2) -> str:
    """
    Sum a list of numbers.

    Args:
        values: List of numbers or numeric strings
        round_decimals: Decimal places for result (default 2)

    Returns:
        JSON with total, count, and values used
    """
    nums = _parse_values(values)
    if not nums:
        return json.dumps({"error": "No valid numeric values", "raw_input": values})
    total = sum(nums)
    return json.dumps({
        "operation": "sum",
        "count": len(nums),
        "values_used": nums,
        "result": round(total, round_decimals),
        "result_raw": total,
    }, indent=2)


@mcp.tool()
def calculate_percent_change(old_value: float, new_value: float, round_decimals: int = 2) -> str:
    """
    Absolute percent change: |new - old| / |old| * 100
    Returns formatted string like '1608.80%'

    Args:
        old_value: Baseline/earlier value
        new_value: New/later value
        round_decimals: Decimal places (default 2)
    """
    if old_value == 0:
        return json.dumps({"error": "old_value is 0, percent change undefined"})
    pct = abs(new_value - old_value) / abs(old_value) * 100
    pct_r = round(pct, round_decimals)
    return json.dumps({
        "operation": "absolute_percent_change",
        "old_value": old_value,
        "new_value": new_value,
        "percent_change": pct_r,
        "formatted": f"{pct_r:.{round_decimals}f}%",
    }, indent=2)


@mcp.tool()
def calculate_geometric_mean(values: list, round_decimals: int = 2) -> str:
    """
    Geometric mean: (v1 * v2 * ... * vn)^(1/n)

    Args:
        values: List of positive numbers
        round_decimals: Decimal places (default 2)
    """
    nums = _parse_values(values)
    if not nums:
        return json.dumps({"error": "No valid numeric values"})
    if any(v <= 0 for v in nums):
        return json.dumps({"error": "Geometric mean requires all positive values", "bad_values": [v for v in nums if v <= 0]})
    log_sum = sum(math.log(v) for v in nums)
    geo = math.exp(log_sum / len(nums))
    return json.dumps({
        "operation": "geometric_mean",
        "count": len(nums),
        "result": round(geo, round_decimals),
        "result_raw": geo,
    }, indent=2)


@mcp.tool()
def calculate_ols_regression(x_values: list, y_values: list, round_decimals: int = 3) -> str:
    """
    OLS linear regression: y = slope * x + intercept
    Returns [slope, intercept] rounded to specified decimals.

    Args:
        x_values: Predictor values (e.g. years as integers)
        y_values: Outcome values (e.g. receipts in billions)
        round_decimals: Decimal places for slope and intercept (default 3)
    """
    import numpy as np

    x = np.array(_parse_values(x_values), dtype=float)
    y = np.array(_parse_values(y_values), dtype=float)

    if len(x) != len(y):
        return json.dumps({"error": f"x and y length mismatch: {len(x)} vs {len(y)}"})
    if len(x) < 2:
        return json.dumps({"error": "Need at least 2 data points"})

    A = np.vstack([x, np.ones(len(x))]).T
    slope, intercept = np.linalg.lstsq(A, y, rcond=None)[0]

    # R-squared — guard against zero variance in y
    ss_res = float(np.sum((y - (slope * x + intercept)) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = (1 - ss_res / ss_tot) if ss_tot > 1e-12 else None

    slope_r = round(float(slope), round_decimals)
    intercept_r = round(float(intercept), round_decimals)

    return json.dumps({
        "operation": "ols_regression",
        "n_points": len(x),
        "slope": slope_r,
        "intercept": intercept_r,
        "r_squared": round(r_squared, 4) if r_squared is not None else "undefined (zero variance)",
        "formatted_answer": f"[{slope_r}, {intercept_r}]",
    }, indent=2)


@mcp.tool()
def calculate_boxcox_transform(value: float, lambda_val: float, round_decimals: int = 4) -> str:
    """
    Box-Cox transform of a single value.
    Formula: (x^lambda - 1) / lambda  if lambda != 0
             ln(x)                     if lambda == 0

    Args:
        value: Positive number to transform
        lambda_val: Box-Cox lambda (e.g. 0.75)
        round_decimals: Decimal places (default 4)
    """
    if value <= 0:
        return json.dumps({"error": f"Box-Cox requires positive value, got {value}"})
    if abs(lambda_val) < 1e-10:
        transformed = math.log(value)
    else:
        transformed = (value ** lambda_val - 1) / lambda_val
    return json.dumps({
        "operation": "boxcox_transform",
        "input_value": value,
        "lambda": lambda_val,
        "result": round(transformed, round_decimals),
        "result_raw": transformed,
    }, indent=2)


@mcp.tool()
def calculate_boxcox_difference(value1: float, value2: float, lambda_val: float, round_decimals: int = 4) -> str:
    """
    Difference between Box-Cox transforms: boxcox(value1, lambda) - boxcox(value2, lambda)

    Args:
        value1: First value (result = bc(value1) - bc(value2))
        value2: Second value
        lambda_val: Box-Cox lambda
        round_decimals: Decimal places (default 4)
    """
    def _bc(v: float, lam: float) -> float:
        if v <= 0:
            raise ValueError(f"Box-Cox requires positive value, got {v}")
        return math.log(v) if abs(lam) < 1e-10 else (v ** lam - 1) / lam

    try:
        bc1, bc2 = _bc(value1, lambda_val), _bc(value2, lambda_val)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    diff = bc1 - bc2
    return json.dumps({
        "operation": "boxcox_difference",
        "value1": value1,
        "value2": value2,
        "lambda": lambda_val,
        "boxcox_value1": round(bc1, round_decimals + 2),
        "boxcox_value2": round(bc2, round_decimals + 2),
        "difference": round(diff, round_decimals),
    }, indent=2)


@mcp.tool()
def calculate_generic(expression: str) -> str:
    """
    Evaluate a safe arithmetic expression.
    Use for calculations not covered by other tools.
    Supports: basic operators, math functions (math.log, math.sqrt, etc.), abs, round, sum, min, max.

    Args:
        expression: Python arithmetic expression e.g. '(36080 / 97181) * 100' or 'math.sqrt(2602)'
    """
    forbidden = ["import", "exec", "eval", "open", "os", "sys", "__"]
    for f in forbidden:
        if f in expression:
            return json.dumps({"error": f"Forbidden token: {f}"})
    allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    allowed.update({"abs": abs, "round": round, "sum": sum, "min": min, "max": max})
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)  # noqa: S307
        return json.dumps({"expression": expression, "result": result}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "expression": expression})
