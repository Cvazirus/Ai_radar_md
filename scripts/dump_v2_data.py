import sys
import json
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from sqlalchemy import text

def dump_data():
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT * FROM item_analysis_v2"))
        columns = result.keys()
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        
        # Serialize datetime objects to string
        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
                elif hasattr(v, 'value'): # Enum
                    row[k] = v.value
                elif isinstance(v, float) or hasattr(v, '__float__'):
                    row[k] = float(v) if v is not None else None
        
        output_file = "/app/scripts/item_analysis_v2_data.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
            
        print(f"Dumped {len(rows)} rows to {output_file}")
    finally:
        db.close()

if __name__ == "__main__":
    dump_data()
