## Data Representation

The **Comfort Room (Restroom)** resource represents a single restroom facility within Rizal Park (Luneta), including its location, operating hours, accessibility, amenities, and current status. This is the core enterprise resource exchanged between the Comfort Room Registry Service and its consumers (the frontend, the Appointment/ Reporting service equivalent, and the Coverage & Monitoring service).


### Resource Schema

| Field | Type | Description |
| :--- | :--- | :--- |
| "restroomId" | integer | Unique identifier for the comfort room |
| "name" | string | Display name / landmark reference |
| "latitude" | number | Latitude coordinate|
| "longitude" | number | Longitude coordinate |
| "operatingHours" | string | Hours the facility is open, |
| "pwdAccessible" | boolean | Whether the facility is PWD-accessible |
| "genderType" | string | Unisex, Male/Female, etc. |
| "amenities" | array of strings | Available facilities, e.g., handwashing station, soap |
| "status" | string | "open", "closed", or "under_maintenance"  |



#### JSON Format
{
  "restroomId": 101,
  "name": "Rizal Monument Comfort Room",
  "latitude": 14.5826,
  "longitude": 120.9787,
  "operatingHours": "06:00-20:00",
  "pwdAccessible": true,
  "genderType": "Unisex",
  "amenities": 
  "handwashing station",
    "soap"
  ,
  "status": "open"
}
<img width="744" height="296" alt="image" src="https://github.com/user-attachments/assets/0ee1de95-440b-4b88-97ef-14b2a78c5c1f" />
### Equivalent XML Representation
<img width="754" height="429" alt="image" src="https://github.com/user-attachments/assets/0e923c07-8a2e-46f7-a5ca-0102506807ff" />

### Part 7: Content Negotiation
### GET /restrooms/{id} supports both JSON and XML responses for the same underlying resource, selected via the standard HTTP Accept header.

### Request JSON

<img width="563" height="537" alt="image" src="https://github.com/user-attachments/assets/9e58d853-e64d-4cb5-9b5f-9bc38577fe01" />

### REQUEST XML
<img width="690" height="579" alt="image" src="https://github.com/user-attachments/assets/ce5aa7c5-f1c5-4570-85fe-c7b0029e9f0b" />

### Implementation
The wants_xml() helper in app.py inspects the Accept header: if it contains application/xml and does not contain application/json, the service serializes the resource to XML using xml.etree.ElementTree; otherwise it defaults to JSON via Flask's jsonify. The same negotiation logic is reused on the POST /restrooms endpoint, so a newly created restroom can also be returned as XML if the client requests it. This was verified in Postman/curl: sending Accept: application/json vs. Accept: application/xml against the same restroomId returns two different Content-Type responses describing the identical resource.

