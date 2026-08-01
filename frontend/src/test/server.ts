import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { demoBrokers } from "./fixtures";

export const server = setupServer(
  http.get("http://localhost:3000/api/demo/brokers", () => HttpResponse.json(demoBrokers)),
);
