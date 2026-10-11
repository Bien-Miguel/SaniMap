# Architecture Documentation

[architecture.pdf](https://github.com/user-attachments/files/31973858/architecture.pdf)


# Comfort Room Mapping API Architecture

This system illustrates the request-response flow of the Comfort Room Mapping API for the Luneta Park Sanitation project, following a gateway-routed microservice pattern with one entry point and two backend services.

**System Overview**

* **Client / Postman:** Represents external requesters (Postman for testing or a front-end app). Initiates requests and receives final responses.
* **API Gateway:** Serves as the single entry point for incoming traffic. Routes `/restrooms` requests to the Comfort Room Registry Service and `/feedback` requests to the Reporting and Feedback Service. Relays each service's response back to the client.
* **Service A – Comfort Room Registry Service:** Manages restroom-related data (location, availability, status) for the `/restrooms` endpoint as the source of truth.
* **Service B – Reporting and Feedback Service:** Handles submission and processing of tourist reports and feedback. Confirms the referenced restroom exists before saving a report.
* **Service-to-Service Communication:** Service B makes a direct REST API call to Service A to validate that a given `restroom_id` exists before saving a report, preventing orphaned feedback.
* **Response Flow:** Backend services return responses to the API Gateway, which forwards the final result to the Client / Postman in JSON (or optionally XML) format.

---

**Services Comparison**

| Item | Service 1 | Service 2 |
| :--- | :--- | :--- |
| **Service Name** | Comfort Room Registry Service | Reporting and Feedback Service |
| **Business Responsibility** | Manages verified restroom information, including locations, operating hours, amenities/accessibility features, and real-time operational status. | Manages user-submitted reports and feedback regarding closed, damaged, or unsanitary restrooms. |
| **Main Resource/Data** | Restroom entity data (`restroom_id`, `name`, `latitude`, `longitude`, `operating_hours`, `accessibility_features`, `status`). | Report and feedback records (`report_id`, `restroom_id`, `issue_type`, `description`, `timestamp`, `status`). |
| **Example Operations** | • `GET /restrooms` (retrieve all CRs)<br>• `GET /restrooms/{id}` (retrieve specific CR)<br>• `POST /restrooms` (add new CR record) | • `POST /feedback` (submit issue report)<br>• `GET /feedback/{restroom_id}` (get feedback history for a CR) |
| **Why Separate?** | Handles master reference data managed primarily by administrators and queried heavily by tourists viewing the map. | Handles user-generated content and influxes of tourist reports. Isolating it ensures high traffic or report spikes do not affect main restroom search availability. |
