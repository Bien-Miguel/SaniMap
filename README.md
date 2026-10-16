# SaniMap_group2_Lab6

---

# Project Overview

## Comfort Room Mapping API for Luneta Park

The **Comfort Room Mapping API** is a service-oriented and microservice-based system designed to improve access to reliable information about comfort rooms within **Rizal Park (Luneta)**. The project addresses the difficulty visitors may experience in finding available and accessible comfort rooms, as well as reporting facilities that are closed, damaged, or unsanitary.

The system is composed of two independent microservices: the **Comfort Room Registry Service** and the **Reporting and Feedback Service**. The Comfort Room Registry Service manages verified restroom information such as location, operating hours, accessibility features, amenities, and current operational status. Meanwhile, the Reporting and Feedback Service manages visitor-submitted reports and feedback concerning restroom conditions.

An **API Gateway** serves as the single entry point for clients and routes requests to the appropriate backend service. Requests involving `/restrooms` are directed to the Comfort Room Registry Service, while `/feedback` requests are handled by the Reporting and Feedback Service. This architecture allows the services to operate independently while still communicating with each other when necessary.

The project uses **REST APIs** for communication and supports both **JSON and XML data exchange** through content negotiation. The system also implements validation and structured error handling to prevent invalid data, malformed requests, and references to non-existent restrooms from being stored.

## React Frontend

The visitor map and staff dashboard are available in [frontend/README.md](frontend/README.md). The app uses React, Leaflet, and OpenStreetMap tiles, and starts in mock-data mode so the UI can be developed without running the backend. It can be switched to the API Gateway using the frontend's environment configuration. Install frontend dependencies from `frontend` with `npm install`, then run `npm run dev` from either the repository root or `frontend`.
