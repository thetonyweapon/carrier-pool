import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { demoBrokers, loadList, sharedRate, sharedRecs } from "./fixtures";

export const server = setupServer(
  http.get("http://localhost:3000/api/demo/brokers", () => HttpResponse.json(demoBrokers)),
  http.get("http://localhost:3000/api/brokers/:broker/loads", () => HttpResponse.json(loadList)),
  http.post("http://localhost:3000/api/demo/auth", () =>
    HttpResponse.json({ access_token: "test-token", token_type: "bearer", broker_id: "broker-a" }),
  ),
  http.get("http://localhost:3000/api/brokers/:broker/shared-pool-policy", ({ params }) =>
    HttpResponse.json({ broker_id: params.broker, enabled: true, policy_revision: 1, attribute_profile: "public-carrier-name-v1" }),
  ),
  http.put("http://localhost:3000/api/brokers/:broker/shared-pool-policy", ({ params }) =>
    HttpResponse.json({ broker_id: params.broker, enabled: true, policy_revision: 1, attribute_profile: "public-carrier-name-v1" }),
  ),
  http.get("http://localhost:3000/api/brokers/:broker/loads/:load/shared-carrier-recommendations", () => HttpResponse.json(sharedRecs)),
  http.get("http://localhost:3000/api/brokers/:broker/loads/:load/shared-carrier-rate-estimate", () => HttpResponse.json(sharedRate)),
);
