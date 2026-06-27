import os
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dineout")

# Mock database
RESTAURANTS = {
    "1": {
        "id": "1",
        "name": "La Piazza",
        "cuisine": "italian",
        "price_range": "$$",
        "location": "Downtown",
        "rating": 4.5,
        "menu": ["Margherita Pizza - $14", "Spaghetti Carbonara - $18", "Tiramisu - $8"]
    },
    "2": {
        "id": "2",
        "name": "Sakura Sushi",
        "cuisine": "japanese",
        "price_range": "$$$",
        "location": "Midtown",
        "rating": 4.8,
        "menu": ["Salmon Sashimi - $22", "Dragon Roll - $16", "Mochi Ice Cream - $6"]
    },
    "3": {
        "id": "3",
        "name": "El Taco Loco",
        "cuisine": "mexican",
        "price_range": "$",
        "location": "West End",
        "rating": 4.2,
        "menu": ["Al Pastor Tacos (3) - $9", "Quesadilla - $11", "Churros - $5"]
    },
    "4": {
        "id": "4",
        "name": "Green Garden",
        "cuisine": "vegetarian",
        "price_range": "$$",
        "location": "Northside",
        "rating": 4.4,
        "menu": ["Vegan Buddha Bowl - $15", "Gluten-Free Pasta - $16", "Avocado Toast - $12"]
    },
    "5": {
        "id": "5",
        "name": "The Steakhouse",
        "cuisine": "steakhouse",
        "price_range": "$$$$",
        "location": "Financial District",
        "rating": 4.7,
        "menu": ["Ribeye Steak - $45", "Filet Mignon - $52", "Crab Cakes - $24"]
    }
}

@mcp.tool
def get_restaurants(cuisine: str = None, price_range: str = None) -> str:
    """Search for restaurants. Optionally filter by cuisine and/or price range.
    
    Args:
        cuisine: The type of cuisine (e.g. 'italian', 'japanese', 'mexican', 'vegetarian', 'steakhouse').
        price_range: The price range (e.g. '$', '$$', '$$$', '$$$$').
    """
    results = []
    for r in RESTAURANTS.values():
        if cuisine and r["cuisine"].lower() != cuisine.lower():
            continue
        if price_range and r["price_range"] != price_range:
            continue
        results.append({
            "id": r["id"],
            "name": r["name"],
            "cuisine": r["cuisine"],
            "price_range": r["price_range"],
            "location": r["location"],
            "rating": r["rating"]
        })
    return json.dumps(results, indent=2)

@mcp.tool
def get_menu(restaurant_id: str) -> str:
    """Get the menu for a specific restaurant by its ID.
    
    Args:
        restaurant_id: The ID of the restaurant (e.g., '1', '2', '3').
    """
    r = RESTAURANTS.get(restaurant_id)
    if not r:
        return f"Error: Restaurant ID {restaurant_id} not found."
    return json.dumps({
        "restaurant_name": r["name"],
        "menu": r["menu"]
    }, indent=2)

@mcp.tool
def make_reservation(restaurant_id: str, date_time: str, party_size: int) -> str:
    """Make a reservation booking at a restaurant.
    
    Args:
        restaurant_id: The ID of the restaurant.
        date_time: The requested date and time (e.g. '2026-06-27 at 7:00 PM').
        party_size: Number of guests.
    """
    r = RESTAURANTS.get(restaurant_id)
    if not r:
        return f"Error: Restaurant ID {restaurant_id} not found."
    
    confirm_id = f"CONF-{os.urandom(2).hex().upper()}"
    return json.dumps({
        "status": "confirmed",
        "restaurant_name": r["name"],
        "date_time": date_time,
        "party_size": party_size,
        "confirmation_id": confirm_id
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
