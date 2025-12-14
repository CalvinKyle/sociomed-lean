from sqlalchemy import create_engine, text
import os

DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL)

def get_recommendations(product_id):
    """
    Returns a dictionary containing cross-sells (consumables) and similar items.
    """
    recommendations = {
        "consumables": [],
        "similar": []
    }
    
    with engine.connect() as conn:
        # 1. Check for defined relationships (Consumables/Accessories)
        query = text("""
            SELECT p.name, pr.relationship_type 
            FROM product_relationships pr
            JOIN products p ON pr.related_product_id = p.id
            WHERE pr.parent_product_id = :pid
        """)
        result = conn.execute(query, {"pid": product_id}).fetchall()
        
        for row in result:
            recommendations["consumables"].append(f"{row[0]} ({row[1]})")

        # 2. Find similar category items (if no direct relationships)
        if not recommendations["consumables"]:
            cat_query = text("""
                SELECT name FROM products 
                WHERE category = (SELECT category FROM products WHERE id = :pid) 
                AND id != :pid LIMIT 2
            """)
            sim_result = conn.execute(cat_query, {"pid": product_id}).fetchall()
            for row in sim_result:
                recommendations["similar"].append(row[0])
                
    return recommendations
