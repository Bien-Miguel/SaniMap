## Part 10 – Validation and Error Handling

The service validates all incoming requests and returns structured, content-negotiated error bodies (JSON or XML, matching the `Accept` header) rather than crashing or returning unstructured stack traces.

### Error Response Matrix

| Scenario | Trigger | HTTP Status | Error Code |
| :--- | :--- | :--- | :--- |
| **Missing required field** | POST body omits a required field (e.g., `latitude`) | `400 Bad Request` | `VALIDATION_ERROR` |
| **Invalid data** | Wrong type/value (e.g., `pwdAccessible` not boolean, `status` not in allowed set) | `400 Bad Request` | `VALIDATION_ERROR` |
| **Malformed JSON** | Request body is not parseable JSON | `400 Bad Request` | `MALFORMED_JSON` |
| **Malformed XML** | Request body is not well-formed XML | `400 Bad Request` | `MALFORMED_XML` |
| **Resource does not exist** | `GET /restrooms/{id}` for an unknown id | `404 Not Found` | `RESOURCE_NOT_FOUND` |
| **Duplicate/conflicting operation** | POST includes a `restroomId` that already exists | `409 Conflict` | `CONFLICT` |
| **Unsupported request media type** | `Content-Type` is neither `application/json` nor `application/xml` | `415 Unsupported Media Type` | `UNSUPPORTED_MEDIA_TYPE` |


### Example — Missing Required Field
### Request
<img width="679" height="321" alt="image" src="https://github.com/user-attachments/assets/5905026e-7ac6-4470-984f-cc49229b1071" />
<img width="671" height="373" alt="image" src="https://github.com/user-attachments/assets/d18fc074-0181-4fc9-be6b-d2a82792287d" />

### Example — Unsupported Media Type
### Request

<img width="684" height="370" alt="image" src="https://github.com/user-attachments/assets/d8555e84-71c3-44dd-a25c-83f9b0dbe240" />
<img width="510" height="333" alt="image" src="https://github.com/user-attachments/assets/399b7bd4-9328-4c2b-95d3-8d96e935501b" />

### Example — Resource Not Found
### Request

<img width="446" height="498" alt="image" src="https://github.com/user-attachments/assets/1e1ccdba-95e2-4001-95a5-f75cc7b35db5" />
<img width="473" height="507" alt="image" src="https://github.com/user-attachments/assets/a04f20fc-6c51-4856-9502-b6baf35cbd67" />


### Implementation
Validation is centralized in validate_restroom(), which checks for presence of all required fields, correct types (latitude/longitude numeric, pwdAccessible boolean, amenities a non-empty list),
and that status is one of the allowed values (open, closed, under_maintenance). Malformed JSON/XML is caught with try/except around the deserialization step, 
so a bad payload returns a structured 400 instead of crashing the service. All error responses go through the same render_resource() helper used for successful responses, so errors honor the client's Accept header just like normal resource responses do. This was verified in Postman across all seven scenarios above, each returning the expected status code and structured error body.
