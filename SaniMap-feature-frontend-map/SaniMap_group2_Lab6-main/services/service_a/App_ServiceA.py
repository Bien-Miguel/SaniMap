from flask import Flask, jsonify, request
from datetime import datetime

app = Flask(__name__)

# Master reference data for public restrooms/comfort rooms
restrooms = [
    {
        "restroom_id": "cr-001",
        "name": "Main Building Ground Floor Restroom",
        "latitude": 14.2134,
        "longitude": 121.1652,
        "operating_hours": "06:00 - 22:00",
        "accessibility_features": ["wheelchair_ramp", "grab_bars"],
        "status": "OPEN"
    },
    {
        "restroom_id": "cr-002",
        "name": "Park Pavilion Restroom",
        "latitude": 14.2140,
        "longitude": 121.1660,
        "operating_hours": "24/7",
        "accessibility_features": ["braille_signage", "wheelchair_ramp"],
        "status": "OPEN"
    }
]

# --- HEALTH CHECK ENDPOINT ---
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "UP",
        "service": "Comfort Room Registry Service",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

# --- API ENDPOINTS ---

# GET /restrooms - Retrieve all CRs
@app.route('/restrooms', methods=['GET'])
def get_restrooms():
    return jsonify(restrooms), 200

# GET /restrooms/<id> - Retrieve a specific CR by ID
@app.route('/restrooms/<string:restroom_id>', methods=['GET'])
def get_restroom_by_id(restroom_id):
    restroom = next((r for r in restrooms if r["restroom_id"] == restroom_id), None)
    if restroom is None:
        return jsonify({"error": "Restroom record not found"}), 404
    return jsonify(restroom), 200

# POST /restrooms - Add a new CR record
@app.route('/restrooms', methods=['POST'])
def add_restroom():
    data = request.get_json() or {}
    
    # Simple validation for required fields
    if "name" not in data or "latitude" not in data or "longitude" not in data:
        return jsonify({"error": "Missing required fields: name, latitude, or longitude"}), 400

    new_restroom = {
        "restroom_id": f"cr-00{len(restrooms) + 1}",
        "name": data["name"],
        "latitude": data["latitude"],
        "longitude": data["longitude"],
        "operating_hours": data.get("operating_hours", "24/7"),
        "accessibility_features": data.get("accessibility_features", []),
        "status": data.get("status", "OPEN")
    }
    
    restrooms.append(new_restroom)
    return jsonify(new_restroom), 201

# Run as an independent microservice on http://localhost:5001
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
