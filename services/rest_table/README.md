## Part 2 – Design the REST API

| Service | Method | Endpoint | Purpose |
| :--- | :--- | :--- | :--- |
| **Comfort Room Registry Service (Service A)** | `GET` | `/health` | Checks whether the Comfort Room Registry Service is running. |
| **Comfort Room Registry Service (Service A)** | `GET` | `/restrooms/{id}` | Retrieves details, location, and facilities of a specific comfort room. |
| **Comfort Room Registry Service (Service A)** | `POST` | `/restrooms` | Adds a new comfort room entry to the park registry (Admin use). |
| **Reporting and Feedback Service (Service B)** | `GET` | `/health` | Checks whether the Reporting and Feedback Service is running. |
| **Reporting and Feedback Service (Service B)** | `GET` | `/feedback/{restroom_id}` | Retrieves all visitor feedback and reports history for a specific comfort room. |
| **Reporting and Feedback Service (Service B)** | `POST` | `/feedback` | Submits a new tourist complaint or issue report regarding facility conditions. |
