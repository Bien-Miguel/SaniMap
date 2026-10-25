## Part 5 – Implement JSON Data Exchange
---

### POST Endpoint – Stage-Labeled Code (Deserialization → Validation → Business Processing → Serialization) 
<img width="579" height="456" alt="image" src="https://github.com/user-attachments/assets/a80d50b3-6661-4754-8cde-9821d7aa73ba" />

### GET Endpoint – JSON Serialization 
<img width="549" height="94" alt="image" src="https://github.com/user-attachments/assets/49163f4b-89bf-4e6b-8487-5df699283711" />

## Postman Test Results 
###  POST /restrooms – Request (Success Case) 

<img width="687" height="175" alt="image" src="https://github.com/user-attachments/assets/45908837-02a2-4f63-a076-ea90ef87f63b" />
### POST /restrooms – Response (201 Created)
<img width="581" height="430" alt="image" src="https://github.com/user-attachments/assets/06388905-4f87-45f6-a641-053d4d25dd43" />

### GET /restrooms – Response (200 OK)
<img width="588" height="418" alt="image" src="https://github.com/user-attachments/assets/c2e1056c-760a-42c4-b6fd-0f5790b1eb19" />

POST /restrooms – Response (400 Bad Request, Validation Failure)
<img width="836" height="325" alt="image" src="https://github.com/user-attachments/assets/7a2251ec-4dea-4e33-9250-3c0791609b5e" />

## Part 5 – JSON Data Exchange Flow
[ Client / Postman ] ──( Raw JSON )──> [ request.get_json() ] ──> Python Dictionary
                                                                         │
[ Client / Postman ] <──( 201 Created ) ── [ jsonify() ] <─── Validation & Storage

When a client sends a POST request to /restrooms with a JSON body, Flask's request.get_json() deserializes the raw JSON into a Python dictionary, turning it into application data the server can work with. The application then validates that required fields (name, latitude, longitude) are present before doing anything with them. Once validation passes, business processing builds a new restroom record,  generating an ID and filling in default values for optional fields like operating_hours, and appends it to the in-memory data store. Finally, the new record is serialized back into JSON using jsonify() and returned to the client with a 201 Created status.

The GET /restrooms endpoint follows the serialization half of this same flow on its own: it takes the current application data (the restrooms list) and directly serializes it into a JSON response with a 200 OK status, so any client can retrieve the current list of comfort rooms.
Together, these two endpoints demonstrate the full JSON data exchange cycle required by Part 5: JSON Request → Deserialization → Application Data → Validation → Business Processing → Serialization.
