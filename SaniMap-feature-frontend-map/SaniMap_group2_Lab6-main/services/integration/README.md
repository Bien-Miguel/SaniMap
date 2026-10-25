## PART 8
### 1. Successful Integrated Transaction 

<img width="803" height="540" alt="image" src="https://github.com/user-attachments/assets/115639b9-bb4f-43cb-b4f3-3ebe5ad4f4de" />

This demonstrates how the entire integration process is carried out: Service B receives a new feedback input, invokes the GET /restrooms/cr-001 endpoint from Service A to confirm that there is indeed a restroom, parses the JSON response, and makes use of the name field (“Main Building Ground Floor Restroom”) from the received response to generate the report. This shows that Service B managed to make the HTTP call and use the response data effectively.

### 2. Restroom Not Found (Failed Integration — Invalid Reference) 

<img width="797" height="476" alt="image" src="https://github.com/user-attachments/assets/49e43576-2c64-41d1-9bd8-4f5d93bc2036" />

This demonstrates that when a tourist submits information or feedback concerning a toilet that is not in the list of registered toilets, the call made by Service B for Service A returns no match, and the system rejects the report and returns an error message RESTROOM_NOT_FOUND instead of silently saving invalid data.

### 3. Dependent Service Unavailable (Failure Handling) 

<img width="798" height="487" alt="image" src="https://github.com/user-attachments/assets/8aae8e67-1d06-4eb2-9752-3f47b735d135" />

This demonstrates that Service A was manually stopped to mimic a situation of outage. When Service B made its usual validation call, the connection immediately failed and the system returned a structured 503 SERVICE_UNAVAILABLE response instead of crashing. 

### 4. Terminal Logs

<img width="894" height="248" alt="image" src="https://github.com/user-attachments/assets/9992256d-2ee2-4b81-b8e3-de42b5d11336" />
<img width="886" height="245" alt="image" src="https://github.com/user-attachments/assets/d847afbb-7c0d-463e-aba1-80acaa65ee74" />

The logs of the terminal in both Service A and Service B show the real flow of the requests or responses in between the two different services: Service A logs the successful GET /restrooms/cr-001 and cr-999, while Service B logs 201, 404, and 503, respectively.
---
## PART 9
### 1. All Three Services Running Independently: 

<img width="904" height="136" alt="image" src="https://github.com/user-attachments/assets/c1471efc-cdc1-4036-b4dd-33ad1b11515c" />
<img width="925" height="136" alt="image" src="https://github.com/user-attachments/assets/fc9f6f1d-3c7d-4132-9f71-073080d93886" />
<img width="912" height="133" alt="image" src="https://github.com/user-attachments/assets/8ac99a14-48d5-4247-a962-c230c493f35c" />

This demonstrates how each of these services, including the gateway, runs as its own independent or separate process.

### 2. Gateway Health Check

<img width="746" height="611" alt="image" src="https://github.com/user-attachments/assets/ac08080a-7766-4c3e-9fda-169f0f4d9c26" />

This demonstrates that the gateway itself is a live and functioning entry point, separate from the two backend services it manages. 

### 3. Aggregated Health Check 

<img width="715" height="478" alt="image" src="https://github.com/user-attachments/assets/20934b7e-448e-4883-95d4-9989362fdd54" />

This indicates that the gateway is constantly monitoring the backend services together in a single call, which is helpful for ensuring that the system is ready for integration testing.

### 4. Gateway Routing to Service A 

<img width="621" height="655" alt="image" src="https://github.com/user-attachments/assets/51cde7e4-e738-4b31-ac77-032109ab5752" />

This demonstrates that the gateway is forwarding a client request to Service A correctly within itself and the client is not communicating on port 5001. 

### 5. Full Integrated Transaction via Gateway 

<img width="605" height="597" alt="image" src="https://github.com/user-attachments/assets/7a1960d4-c49d-4fda-b98d-34ef99cf46d6" />

This demonstrates how Service A, Service B, and the gateway work together as one complete system. It is shown how a request enters into the system through the gateway, is routed to Service B, which independently calls Service A, deserializes its response, and returns the enriched result back to the client through the gateway.

### Why the gateway exists:
The API Gateway provides a single, consistent entry point (port 5000) for all client requests, so tourists, Postman testers, or a future frontend never need to know the individual ports of Service A (5001) or Service B (5002) directly.

### Which services it routes to:
/restrooms and /restrooms/{id} → Comfort Room Registry Service (Service A)
/feedback and /feedback/{restroom_id} → Reporting and Feedback Service (Service B)

### How it simplifies client interaction:
This simplifies client interaction because it only requires one address (port 5000). The gateway also centralizes failure handling if either backend service is unreachable. The gateway also returns a consistent 503 Service Unavailable response rather than exposing raw connection errors to the client.


