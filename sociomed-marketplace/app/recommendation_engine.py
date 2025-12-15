from sqlalchemy import create_engine, text
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_recommendations(engine, product_id):
    """
    Returns a dictionary containing cross-sells (consumables) and similar items.
    Uses the shared database engine connection.
    """
    recommendations = {
        "consumables": [],
        "similar": []
    }
    
    try:
        with engine.connect() as conn:
            # 1. Check for defined relationships (Consumables/Accessories)
            # SCHEMA FIX: Used inventory.product_relationships and correct columns (child_product_id)
            rel_query = text("""
                SELECT p.name, pr.relationship_type 
                FROM inventory.product_relationships pr
                JOIN inventory.products p ON pr.child_product_id = p.product_id
                WHERE pr.parent_product_id = :pid
                LIMIT 5
            """)
            rel_result = conn.execute(rel_query, {"pid": product_id}).fetchall()
            
            for row in rel_result:
                # Format: "Surgical Gloves (CONSUMABLE)"
                recommendations["consumables"].append(f"{row[0]} ({row[1]})")

            # 2. Find similar category items (if direct relationships are scarce)
            # SCHEMA FIX: Used inventory.products and product_id
            if len(recommendations["consumables"]) < 3:
                cat_query = text("""
                    SELECT name FROM inventory.products 
                    WHERE category = (SELECT category FROM inventory.products WHERE product_id = :pid) 
                    AND product_id != :pid 
                    LIMIT 3
                """)
                sim_result = conn.execute(cat_query, {"pid": product_id}).fetchall()
                for row in sim_result:
                    recommendations["similar"].append(row[0])
                    
    except Exception as e:
        logger.error(f"Error fetching recommendations for Product ID {product_id}: {e}")
        
    return recommendations
