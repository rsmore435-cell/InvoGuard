import json
from mcp.server.fastmcp import FastMCP

# Create a FastMCP server named "VendorProfileService"
mcp = FastMCP("VendorProfileService")

@mcp.tool()
def get_vendor_profile(vendor_name: str) -> str:
    """Fetch vendor profile configuration including contract terms, discount tiers, and registered tax details.
    
    Args:
        vendor_name: The legal name of the vendor/contractor to look up.
        
    Returns:
        A JSON string containing tier, discount_rate, tax_id, and registration status.
    """
    profiles = {
        "Acme Corp": {"tier": "Gold", "discount_rate": 0.10, "tax_id": "TX-12345", "status": "ACTIVE"},
        "Globex": {"tier": "Silver", "discount_rate": 0.05, "tax_id": "TX-67890", "status": "ACTIVE"},
        "Initech": {"tier": "Bronze", "discount_rate": 0.0, "tax_id": "TX-11111", "status": "ACTIVE"},
        "Cyberdyne": {"tier": "Gold", "discount_rate": 0.12, "tax_id": "TX-99999", "status": "SUSPENDED"}
    }
    
    # Return the profile or a default standard profile if not registered
    profile = profiles.get(vendor_name, {"tier": "Standard", "discount_rate": 0.0, "tax_id": "UNKNOWN", "status": "UNREGISTERED"})
    return json.dumps(profile)

if __name__ == "__main__":
    # Start the server on stdio
    mcp.run()
