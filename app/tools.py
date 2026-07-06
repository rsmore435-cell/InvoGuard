import sys
import os
import json
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

def query_contract_registry(vendor_name: str) -> dict:
    """Queries the Mock Contract Registry database for contract terms and maximum invoice amount limits.

    Args:
        vendor_name: The legal name of the vendor (e.g. 'Acme Corp', 'Globex', 'Initech').

    Returns:
        A dictionary containing the vendor's contracted unit rates per item and their maximum invoice spending limit.
    """
    contracts = {
        "Acme Corp": {
            "rates": {
                "Widget A": 10.00,
                "Service B": 150.00,
                "Consulting": 100.00
            },
            "max_invoice_limit": 10000.00
        },
        "Globex": {
            "rates": {
                "Consulting": 200.00,
                "Server Hosting": 500.00
            },
            "max_invoice_limit": 25000.00
        },
        "Initech": {
            "rates": {
                "Stapler Red": 15.00,
                "Consulting": 80.00
            },
            "max_invoice_limit": 5000.00
        }
    }
    # Return the rates for the requested vendor, or empty if unknown
    return contracts.get(vendor_name, {"rates": {}, "max_invoice_limit": 1000.00})


def verify_math_calculations(code_to_execute: str) -> dict:
    """Safely executes mathematical validation code to verify subtotals, tax math, and final totals.

    Args:
        code_to_execute: A python snippet defining calculations or boolean assertions (e.g., 'subtotal = 10 * 15\\ntax = subtotal * 0.05\\ntotal = subtotal + tax').

    Returns:
        A dictionary containing the status of execution and any computed variables.
    """
    # Defensive checks to prevent python code injection or unsafe operations
    allowed_chars = set("0123456789.+-*/()=<>!&| \n\t_[]{},:\"'aBcDeFgHiJkLmNoPqRsTuVwXyZ")
    if not all(c in allowed_chars for c in code_to_execute):
        return {"status": "error", "error": "Unsafe characters detected in math expression."}

    # Block common malicious functions and imports
    prohibited = ["import", "eval", "exec", "getattr", "setattr", "delattr", "locals", "globals", "open", "system", "subprocess", "os", "sys", "__"]
    for word in prohibited:
        if word in code_to_execute:
            return {"status": "error", "error": f"Prohibited operation '{word}' detected."}

    try:
        # Execute the math snippet in a fully sandboxed/empty namespace
        namespace = {}
        exec(code_to_execute, {"__builtins__": None}, namespace)
        # Convert any float or int values to standard formats for JSON serialization
        serializable_namespace = {}
        for k, v in namespace.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                serializable_namespace[k] = v
        return {"status": "success", "results": serializable_namespace}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# Configure the local MCP server toolset pointing to our mcp_server.py
current_dir = os.path.dirname(os.path.abspath(__file__))
mcp_server_path = os.path.join(current_dir, "mcp_server.py")

vendor_mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[mcp_server_path]
        )
    )
)
